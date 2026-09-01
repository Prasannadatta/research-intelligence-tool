"""Tests for saved author and grant search definitions."""

from __future__ import annotations

import asyncio
from pathlib import Path

from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.core.config import get_settings
from app.db.base import Base
from app.db.models import SavedSearch  # noqa: F401 - ensure model registration
from app.db.session import get_db_session
from app.main import app


def _author_payload(order: tuple[str, str] = ("c1", "c2")) -> dict:
    names = {
        "c1": ("John Smith", "A1"),
        "c2": ("Jane Doe", "A2"),
    }
    return {
        "search_type": "authors",
        "payload": {
            "authors": [
                {
                    "canonical_author_id": author_id,
                    "display_name": names[author_id][0],
                    "provider": "openalex",
                    "provider_author_id": names[author_id][1],
                }
                for author_id in order
            ],
            "active_author_ids": list(order),
            "filters": {
                "from_year": 2020,
                "sources": ["OpenAlex"],
                "institutions": ["UC Berkeley"],
            },
            "excluded_work_ids": ["W2", "W1"],
        },
    }


def _grant_payload(grant_number: str = "R01GM123456", filters: dict | None = None) -> dict:
    return {
        "search_type": "grant",
        "payload": {
            "grant_number": grant_number,
            "provider": "openalex",
            "filters": filters or {"venues": ["Nature Medicine"]},
        },
        "metadata": {"funder_name": "NIH"},
    }


def _client(tmp_path, monkeypatch):
    db_path = tmp_path / "saved_searches.db"
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
    client = TestClient(app)
    return client, engine


def test_save_author_search_and_duplicate_order_upserts(tmp_path, monkeypatch):
    client, engine = _client(tmp_path, monkeypatch)
    try:
        first = client.post("/api/saved-searches", json=_author_payload(("c1", "c2")))
        second = client.post("/api/saved-searches", json=_author_payload(("c2", "c1")))

        assert first.status_code == 200
        assert second.status_code == 200
        assert first.json()["id"] == second.json()["id"]
        assert second.json()["excluded_work_ids"] == ["W1", "W2"]
        assert second.json()["payload"]["filters"]["institutions"] == ["UC Berkeley"]

        listing = client.get("/api/saved-searches", params={"type": "authors"})
        assert listing.status_code == 200
        assert len(listing.json()["items"]) == 1
    finally:
        app.dependency_overrides.clear()
        asyncio.run(engine.dispose())


def test_save_grant_search_normalizes_duplicates_and_keeps_metadata(tmp_path, monkeypatch):
    client, engine = _client(tmp_path, monkeypatch)
    try:
        first = client.post("/api/saved-searches", json=_grant_payload("R01 GM-123456"))
        second = client.post("/api/saved-searches", json=_grant_payload("r01gm123456"))

        assert first.status_code == 200
        assert second.status_code == 200
        assert first.json()["id"] == second.json()["id"]
        assert second.json()["display_name"] == "r01gm123456"
        assert second.json()["metadata"] == {"funder_name": "NIH"}

        listing = client.get("/api/saved-searches", params={"type": "grant"})
        assert len(listing.json()["items"]) == 1
    finally:
        app.dependency_overrides.clear()
        asyncio.run(engine.dispose())


def test_filters_participate_in_canonical_key(tmp_path, monkeypatch):
    client, engine = _client(tmp_path, monkeypatch)
    try:
        one = client.post(
            "/api/saved-searches",
            json=_grant_payload(filters={"from_year": 2020}),
        )
        two = client.post(
            "/api/saved-searches",
            json=_grant_payload(filters={"from_year": 2021}),
        )

        assert one.status_code == 200
        assert two.status_code == 200
        assert one.json()["id"] != two.json()["id"]
    finally:
        app.dependency_overrides.clear()
        asyncio.run(engine.dispose())


def test_list_type_view_count_sorting_and_delete(tmp_path, monkeypatch):
    client, engine = _client(tmp_path, monkeypatch)
    try:
        author = client.post("/api/saved-searches", json=_author_payload()).json()
        grant = client.post("/api/saved-searches", json=_grant_payload()).json()

        viewed = client.post(f"/api/saved-searches/{grant['id']}/view")
        assert viewed.status_code == 200
        assert viewed.json()["view_count"] == 1
        assert viewed.json()["last_viewed_at"] is not None

        sorted_response = client.get(
            "/api/saved-searches",
            params={"sort_by": "view_count", "sort_direction": "desc"},
        )
        assert [item["id"] for item in sorted_response.json()["items"]][:2] == [
            grant["id"],
            author["id"],
        ]

        assert client.delete(f"/api/saved-searches/{grant['id']}").status_code == 204
        grants = client.get("/api/saved-searches", params={"type": "grant"}).json()
        authors = client.get("/api/saved-searches", params={"type": "authors"}).json()
        assert grants["items"] == []
        assert len(authors["items"]) == 1
    finally:
        app.dependency_overrides.clear()
        asyncio.run(engine.dispose())


def test_malformed_payload_rejected(tmp_path, monkeypatch):
    client, engine = _client(tmp_path, monkeypatch)
    try:
        response = client.post(
            "/api/saved-searches",
            json={"search_type": "authors", "payload": {"authors": []}},
        )
        assert response.status_code == 422
    finally:
        app.dependency_overrides.clear()
        asyncio.run(engine.dispose())


def test_saved_searches_migration_runs(tmp_path, monkeypatch):
    db_path = tmp_path / "migration.db"
    monkeypatch.setenv("DATABASE_URL", f"sqlite+aiosqlite:///{db_path}")
    get_settings.cache_clear()

    config = Config(str(Path(__file__).resolve().parents[1] / "alembic.ini"))
    config.set_main_option(
        "script_location",
        str(Path(__file__).resolve().parents[1] / "alembic"),
    )
    command.upgrade(config, "008_saved_searches")

    async def assert_table_exists() -> None:
        engine = create_async_engine(f"sqlite+aiosqlite:///{db_path}")
        try:
            async with engine.connect() as conn:
                rows = await conn.execute(
                    select(SavedSearch.__table__.c.search_type).select_from(SavedSearch.__table__)
                )
                assert rows.all() == []
        finally:
            await engine.dispose()

    asyncio.run(assert_table_exists())
