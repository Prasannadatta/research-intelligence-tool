"""Tests for the data updater API and provider request layer."""

from __future__ import annotations

import asyncio
import uuid
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import AsyncMock

import httpx
import pytest
from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.core.config import get_settings
from app.db.base import Base
from app.db.models import (
    CanonicalAuthor,
    CanonicalAuthorInstitution,
    DataUpdateJob,
    ProviderSearchCache,
    SavedSearch,
)
from app.db.session import get_db_session
from app.integrations import rate_limited_http
from app.main import app


def _client(tmp_path, monkeypatch):
    db_path = tmp_path / "data_updater.db"
    monkeypatch.setenv("DATABASE_URL", f"sqlite+aiosqlite:///{db_path}")
    get_settings.cache_clear()

    engine = create_async_engine(
        f"sqlite+aiosqlite:///{db_path}",
        connect_args={"check_same_thread": False},
    )
    session_factory = async_sessionmaker(engine, expire_on_commit=False)

    async def setup() -> None:
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

    asyncio.run(setup())

    async def override_session():
        async with session_factory() as session:
            yield session

    app.dependency_overrides[get_db_session] = override_session
    return TestClient(app), engine, session_factory


def test_categories_list_refreshable_datasets(tmp_path, monkeypatch):
    client, engine, _session_factory = _client(tmp_path, monkeypatch)
    try:
        response = client.get("/api/data-updater/categories")

        assert response.status_code == 200
        keys = {item["key"] for item in response.json()["items"]}
        assert {
            "authors",
            "author_affiliations",
            "institutions",
            "author_publications",
            "publications",
            "publication_metadata",
            "citation_counts",
            "grant_funding",
        }.issubset(keys)
    finally:
        app.dependency_overrides.clear()
        asyncio.run(engine.dispose())


def test_run_inline_provider_cache_cleanup_job(tmp_path, monkeypatch):
    client, engine, session_factory = _client(tmp_path, monkeypatch)

    async def seed_cache() -> None:
        from datetime import datetime, timedelta, timezone
        import uuid

        async with session_factory() as session:
            session.add(
                ProviderSearchCache(
                    id=uuid.uuid4(),
                    cache_key="expired",
                    provider="openalex",
                    entity="works",
                    normalized_query="q",
                    filters=None,
                    cursor=None,
                    response={"items": []},
                    expires_at=datetime.now(timezone.utc) - timedelta(seconds=10),
                )
            )
            await session.commit()

    asyncio.run(seed_cache())

    try:
        response = client.post(
            "/api/data-updater/refresh",
            json={
                "mode": "dataset",
                "dataset": "provider_search_cache",
                "stale_only": True,
                "run_inline": True,
            },
        )

        assert response.status_code == 200
        body = response.json()
        assert body["status"] == "succeeded"
        assert body["processed_records"] == 1
        assert body["updated_count"] == 1

        detail = client.get(f"/api/data-updater/jobs/{body['id']}")
        assert detail.status_code == 200
        assert detail.json()["records"][0]["status"] == "updated"
    finally:
        app.dependency_overrides.clear()
        asyncio.run(engine.dispose())


def test_user_facing_search_and_saved_search_options(tmp_path, monkeypatch):
    client, engine, session_factory = _client(tmp_path, monkeypatch)

    async def seed() -> None:
        async with session_factory() as session:
            author_id = uuid.uuid4()
            session.add(
                CanonicalAuthor(
                    id=author_id,
                    preferred_name="John Preskill",
                    normalized_name="john preskill",
                    surname="preskill",
                    first_initial="j",
                )
            )
            session.add(
                CanonicalAuthorInstitution(
                    canonical_author_id=author_id,
                    institution_key="caltech",
                    institution_name="Caltech",
                    country_code="US",
                    is_current=True,
                )
            )
            session.add(
                SavedSearch(
                    id=uuid.uuid4(),
                    search_type="authors",
                    display_name="Quantum Error Correction Researchers",
                    canonical_key="authors:test",
                    payload={
                        "authors": [
                            {
                                "canonical_author_id": str(author_id),
                                "display_name": "John Preskill",
                            }
                        ],
                        "active_author_ids": [str(author_id)],
                    },
                    applied_filters={},
                    provider_context={},
                )
            )
            await session.commit()

    asyncio.run(seed())

    try:
        search_response = client.get("/api/data-updater/search", params={"q": "Preskill"})
        assert search_response.status_code == 200
        search_items = search_response.json()["items"]
        assert search_items[0]["title"] == "John Preskill"
        assert search_items[0]["type"] == "author"

        saved_response = client.get("/api/data-updater/saved-searches")
        assert saved_response.status_code == 200
        assert saved_response.json()["items"][0]["name"] == "Quantum Error Correction Researchers"
    finally:
        app.dependency_overrides.clear()
        asyncio.run(engine.dispose())


def test_saved_search_refresh_uses_active_author_ids(tmp_path, monkeypatch):
    client, engine, session_factory = _client(tmp_path, monkeypatch)
    created = {}

    async def seed() -> None:
        async with session_factory() as session:
            active_author_id = uuid.uuid4()
            inactive_author_id = uuid.uuid4()
            saved_search_id = uuid.uuid4()
            for author_id, name in (
                (active_author_id, "Active Author"),
                (inactive_author_id, "Inactive Author"),
            ):
                session.add(
                    CanonicalAuthor(
                        id=author_id,
                        preferred_name=name,
                        normalized_name=name.lower(),
                    )
                )
            session.add(
                SavedSearch(
                    id=saved_search_id,
                    search_type="authors",
                    display_name="Selected Authors",
                    canonical_key="authors:selected",
                    payload={
                        "authors": [
                            {
                                "canonical_author_id": str(active_author_id),
                                "display_name": "Active Author",
                            },
                            {
                                "canonical_author_id": str(inactive_author_id),
                                "display_name": "Inactive Author",
                            },
                        ],
                        "active_author_ids": [str(active_author_id)],
                    },
                    applied_filters={},
                    provider_context={},
                )
            )
            await session.commit()
            created["saved_search_id"] = str(saved_search_id)
            created["active_author_id"] = str(active_author_id)
            created["inactive_author_id"] = str(inactive_author_id)

    asyncio.run(seed())

    async def noop_background(_job_id: str) -> None:
        return None

    monkeypatch.setattr("app.services.data_updater.service.run_data_update_job", noop_background)

    try:
        response = client.post(
            "/api/data-updater/refresh/saved-search",
            json={"saved_search_id": created["saved_search_id"]},
        )
        assert response.status_code == 200
        ids_by_dataset = response.json()["metadata"]["record_ids_by_dataset"]
        assert ids_by_dataset["authors"] == [created["active_author_id"]]
        assert created["inactive_author_id"] not in ids_by_dataset["authors"]
    finally:
        app.dependency_overrides.clear()
        asyncio.run(engine.dispose())


def test_pause_and_cancel_job_controls(tmp_path, monkeypatch):
    client, engine, session_factory = _client(tmp_path, monkeypatch)
    job_id = uuid.uuid4()

    async def seed() -> None:
        async with session_factory() as session:
            session.add(
                DataUpdateJob(
                    id=job_id,
                    mode="all_stale",
                    status="running",
                    created_at=datetime.now(timezone.utc),
                    updated_at=datetime.now(timezone.utc),
                )
            )
            await session.commit()

    asyncio.run(seed())

    try:
        pause_response = client.post(f"/api/data-updater/jobs/{job_id}/pause")
        assert pause_response.status_code == 200
        assert pause_response.json()["status"] == "pause_requested"

        cancel_response = client.post(f"/api/data-updater/jobs/{job_id}/cancel")
        assert cancel_response.status_code == 200
        assert cancel_response.json()["status"] == "cancel_requested"
    finally:
        app.dependency_overrides.clear()
        asyncio.run(engine.dispose())


def test_record_mode_requires_record_id(tmp_path, monkeypatch):
    client, engine, _session_factory = _client(tmp_path, monkeypatch)
    try:
        response = client.post(
            "/api/data-updater/refresh",
            json={"mode": "record", "dataset": "authors"},
        )
        assert response.status_code == 422
    finally:
        app.dependency_overrides.clear()
        asyncio.run(engine.dispose())


def test_data_updater_migration_runs(tmp_path, monkeypatch):
    db_path = tmp_path / "migration.db"
    monkeypatch.setenv("DATABASE_URL", f"sqlite+aiosqlite:///{db_path}")
    get_settings.cache_clear()

    config = Config(str(Path(__file__).resolve().parents[1] / "alembic.ini"))
    config.set_main_option(
        "script_location",
        str(Path(__file__).resolve().parents[1] / "alembic"),
    )
    command.upgrade(config, "009_data_update_jobs")

    async def assert_table_exists() -> None:
        engine = create_async_engine(f"sqlite+aiosqlite:///{db_path}")
        try:
            async with engine.connect() as conn:
                rows = await conn.execute(
                    select(DataUpdateJob.__table__.c.status).select_from(DataUpdateJob.__table__)
                )
                assert rows.all() == []
        finally:
            await engine.dispose()

    asyncio.run(assert_table_exists())


@pytest.mark.asyncio
async def test_provider_get_retries_429_retry_after(monkeypatch):
    monkeypatch.setenv("EXTERNAL_API_DEFAULT_MAX_RETRIES", "1")
    monkeypatch.setenv("EXTERNAL_API_BACKOFF_BASE_SECONDS", "0")
    monkeypatch.setenv("OPENALEX_RATE_LIMIT_MIN_INTERVAL_SECONDS", "0")
    get_settings.cache_clear()
    await rate_limited_http.reset_provider_limiters_for_tests()

    calls = []

    class FakeClient:
        def __init__(self, **_kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            return None

        async def get(self, url, params=None):
            calls.append((url, params))
            request = httpx.Request("GET", url)
            if len(calls) == 1:
                return httpx.Response(
                    429,
                    headers={"Retry-After": "0"},
                    request=request,
                )
            return httpx.Response(200, json={"ok": True}, request=request)

    sleep = AsyncMock()
    monkeypatch.setattr(rate_limited_http.httpx, "AsyncClient", FakeClient)
    monkeypatch.setattr(rate_limited_http.asyncio, "sleep", sleep)

    response = await rate_limited_http.provider_get(
        "openalex",
        "https://api.openalex.org/test",
        params={"q": "x"},
        timeout=1,
    )

    assert response.status_code == 200
    assert len(calls) == 2
    sleep.assert_awaited()
