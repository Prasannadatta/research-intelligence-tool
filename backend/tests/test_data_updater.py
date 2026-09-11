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

        # Repeat cancel finalizes orphaned cancel_requested.
        finalize_response = client.post(f"/api/data-updater/jobs/{job_id}/cancel")
        assert finalize_response.status_code == 200
        assert finalize_response.json()["status"] == "cancelled"
    finally:
        app.dependency_overrides.clear()
        asyncio.run(engine.dispose())


@pytest.mark.asyncio
async def test_worker_honors_cancel_during_target_listing(tmp_path, monkeypatch):
    """Cancel during listing/prepare must stop before processing targets."""
    from unittest.mock import AsyncMock

    from app.services.data_updater.repository import DataUpdaterRepository
    from app.services.data_updater.service import DataUpdaterService

    db_path = tmp_path / "cancel_list.db"
    engine = create_async_engine(
        f"sqlite+aiosqlite:///{db_path}",
        connect_args={"check_same_thread": False},
    )
    session_factory = async_sessionmaker(engine, expire_on_commit=False)

    job_id = uuid.uuid4()
    process_calls: list[str] = []

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    async with session_factory() as session:
        session.add(
            DataUpdateJob(
                id=job_id,
                mode="dataset",
                dataset="provider_search_cache",
                status="queued",
                metadata_={"stale_only": False},
                created_at=datetime.now(timezone.utc),
                updated_at=datetime.now(timezone.utc),
            )
        )
        await session.commit()

    async with session_factory() as session:
        service = DataUpdaterService(session)

        async def list_and_cancel(dataset, ttl_seconds=None, record_ids=None, stale_only=True):
            await session.commit()
            async with session_factory() as control:
                job = await control.get(DataUpdateJob, job_id)
                job.status = "cancel_requested"
                await control.commit()
            return [{"record_id": f"r{i}", "source": None} for i in range(3)]

        async def track_process(job, dataset, target):
            process_calls.append(target["record_id"])
            await DataUpdaterRepository(session).add_record_result(
                job=job,
                dataset=dataset,
                record_id=target["record_id"],
                status="updated",
                message="ok",
            )

        service.repo.list_refresh_targets = list_and_cancel
        service.repo.completed_record_keys = AsyncMock(return_value=set())
        service._process_target = track_process
        await service.run_job(str(job_id))

    async with session_factory() as session:
        job = await session.get(DataUpdateJob, job_id)
        assert job is not None
        assert job.status == "cancelled"
        assert job.processed_records == 0
        assert process_calls == []

    await engine.dispose()


@pytest.mark.asyncio
async def test_worker_honors_pause_during_target_listing(tmp_path, monkeypatch):
    """Pause during listing must not be overwritten by mark_job_started."""
    from unittest.mock import AsyncMock

    from app.services.data_updater.repository import DataUpdaterRepository
    from app.services.data_updater.service import DataUpdaterService

    db_path = tmp_path / "pause_list.db"
    engine = create_async_engine(
        f"sqlite+aiosqlite:///{db_path}",
        connect_args={"check_same_thread": False},
    )
    session_factory = async_sessionmaker(engine, expire_on_commit=False)

    job_id = uuid.uuid4()
    process_calls: list[str] = []

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    async with session_factory() as session:
        session.add(
            DataUpdateJob(
                id=job_id,
                mode="dataset",
                dataset="provider_search_cache",
                status="queued",
                metadata_={"stale_only": False},
                created_at=datetime.now(timezone.utc),
                updated_at=datetime.now(timezone.utc),
            )
        )
        await session.commit()

    async with session_factory() as session:
        service = DataUpdaterService(session)

        async def list_and_pause(dataset, ttl_seconds=None, record_ids=None, stale_only=True):
            # Release any worker write lock before the control session updates.
            await session.commit()
            async with session_factory() as control:
                job = await control.get(DataUpdateJob, job_id)
                job.status = "pause_requested"
                await control.commit()
            return [{"record_id": f"r{i}", "source": None} for i in range(3)]

        async def track_process(job, dataset, target):
            process_calls.append(target["record_id"])
            await DataUpdaterRepository(session).add_record_result(
                job=job,
                dataset=dataset,
                record_id=target["record_id"],
                status="updated",
                message="ok",
            )

        service.repo.list_refresh_targets = list_and_pause
        service.repo.completed_record_keys = AsyncMock(return_value=set())
        service._process_target = track_process
        await service.run_job(str(job_id))

    async with session_factory() as session:
        job = await session.get(DataUpdateJob, job_id)
        assert job is not None
        assert job.status == "paused"
        assert job.processed_records == 0
        assert process_calls == []

    await engine.dispose()


@pytest.mark.asyncio
async def test_worker_pause_resume_preserves_progress_and_cancel_stops(tmp_path, monkeypatch):
    from unittest.mock import AsyncMock

    from app.services.data_updater.repository import DataUpdaterRepository
    from app.services.data_updater.service import DataUpdaterService

    db_path = tmp_path / "pause_resume.db"
    engine = create_async_engine(
        f"sqlite+aiosqlite:///{db_path}",
        connect_args={"check_same_thread": False},
    )
    session_factory = async_sessionmaker(engine, expire_on_commit=False)

    job_id = uuid.uuid4()
    targets = [{"record_id": f"r{i}", "source": None} for i in range(4)]

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    async with session_factory() as session:
        session.add(
            DataUpdateJob(
                id=job_id,
                mode="dataset",
                dataset="provider_search_cache",
                status="queued",
                metadata_={"stale_only": False},
                created_at=datetime.now(timezone.utc),
                updated_at=datetime.now(timezone.utc),
            )
        )
        await session.commit()

    first_pass: list[str] = []

    async with session_factory() as session:
        service = DataUpdaterService(session)

        async def process_then_pause(job, dataset, target):
            first_pass.append(target["record_id"])
            await DataUpdaterRepository(session).add_record_result(
                job=job,
                dataset=dataset,
                record_id=target["record_id"],
                status="updated",
                message="ok",
            )
            if len(first_pass) == 1:
                await session.commit()
                async with session_factory() as control:
                    row = await control.get(DataUpdateJob, job_id)
                    row.status = "pause_requested"
                    await control.commit()

        service.repo.list_refresh_targets = AsyncMock(return_value=list(targets))
        service.repo.completed_record_keys = AsyncMock(return_value=set())
        service._process_target = process_then_pause
        await service.run_job(str(job_id))

    async with session_factory() as session:
        job = await session.get(DataUpdateJob, job_id)
        assert job.status == "paused"
        assert job.processed_records == 1
        assert first_pass == ["r0"]
        job.status = "queued"
        await session.commit()

    second_pass: list[str] = []
    async with session_factory() as session:
        service = DataUpdaterService(session)
        completed = await DataUpdaterRepository(session).completed_record_keys(job_id)

        async def process_remaining(job, dataset, target):
            second_pass.append(target["record_id"])
            await DataUpdaterRepository(session).add_record_result(
                job=job,
                dataset=dataset,
                record_id=target["record_id"],
                status="updated",
                message="ok",
            )

        service.repo.list_refresh_targets = AsyncMock(return_value=list(targets))
        service.repo.completed_record_keys = AsyncMock(return_value=completed)
        service._process_target = process_remaining
        await service.run_job(str(job_id))

    async with session_factory() as session:
        job = await session.get(DataUpdateJob, job_id)
        assert job.status == "succeeded"
        assert job.processed_records == 4
        assert second_pass == ["r1", "r2", "r3"]

    # Fresh cancel mid-run
    cancel_job_id = uuid.uuid4()
    cancel_calls: list[str] = []
    async with session_factory() as session:
        session.add(
            DataUpdateJob(
                id=cancel_job_id,
                mode="dataset",
                dataset="provider_search_cache",
                status="queued",
                metadata_={"stale_only": False},
                created_at=datetime.now(timezone.utc),
                updated_at=datetime.now(timezone.utc),
            )
        )
        await session.commit()

    async with session_factory() as session:
        service = DataUpdaterService(session)

        async def process_then_cancel(job, dataset, target):
            cancel_calls.append(target["record_id"])
            await DataUpdaterRepository(session).add_record_result(
                job=job,
                dataset=dataset,
                record_id=target["record_id"],
                status="updated",
                message="ok",
            )
            if len(cancel_calls) == 2:
                await session.commit()
                async with session_factory() as control:
                    row = await control.get(DataUpdateJob, cancel_job_id)
                    row.status = "cancel_requested"
                    await control.commit()

        service.repo.list_refresh_targets = AsyncMock(return_value=list(targets))
        service.repo.completed_record_keys = AsyncMock(return_value=set())
        service._process_target = process_then_cancel
        await service.run_job(str(cancel_job_id))

    async with session_factory() as session:
        job = await session.get(DataUpdateJob, cancel_job_id)
        assert job.status == "cancelled"
        assert job.processed_records == 2
        assert cancel_calls == ["r0", "r1"]

    await engine.dispose()


def test_resume_and_cancel_paused_job_via_api(tmp_path, monkeypatch):
    client, engine, session_factory = _client(tmp_path, monkeypatch)
    job_id = uuid.uuid4()
    started = []

    async def seed() -> None:
        async with session_factory() as session:
            session.add(
                DataUpdateJob(
                    id=job_id,
                    mode="all_stale",
                    status="paused",
                    processed_records=3,
                    total_records=10,
                    created_at=datetime.now(timezone.utc),
                    updated_at=datetime.now(timezone.utc),
                )
            )
            await session.commit()

    async def capture_background(job_id_arg: str) -> None:
        started.append(job_id_arg)

    asyncio.run(seed())
    monkeypatch.setattr(
        "app.services.data_updater.service.run_data_update_job",
        capture_background,
    )

    try:
        resume_response = client.post(f"/api/data-updater/jobs/{job_id}/resume")
        assert resume_response.status_code == 200
        assert resume_response.json()["status"] == "queued"
        assert resume_response.json()["processed_records"] == 3
        assert started == [str(job_id)]

        # Force paused again then cancel immediately.
        async def mark_paused() -> None:
            async with session_factory() as session:
                job = await session.get(DataUpdateJob, job_id)
                job.status = "paused"
                await session.commit()

        asyncio.run(mark_paused())
        cancel_response = client.post(f"/api/data-updater/jobs/{job_id}/cancel")
        assert cancel_response.status_code == 200
        assert cancel_response.json()["status"] == "cancelled"
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
