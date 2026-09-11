"""Tests for saved author and grant search definitions."""

from __future__ import annotations

import asyncio
from pathlib import Path

from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.core.config import get_settings
from app.db.base import Base
from app.db.models import SavedSearch  # noqa: F401 - ensure model registration
from app.db.session import get_db_session
from app.main import app


def _author_payload(
    order: tuple[str, str] = ("c1", "c2"),
    *,
    filters: dict | None = None,
    display_name: str | None = None,
    excluded_work_ids: list[str] | None = None,
) -> dict:
    names = {
        "c1": ("John Smith", "A1"),
        "c2": ("Jane Doe", "A2"),
        "c3": ("Alex Roe", "A3"),
    }
    body = {
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
            "filters": filters
            if filters is not None
            else {
                "from_year": 2020,
                "sources": ["OpenAlex"],
                "institutions": ["UC Berkeley"],
            },
            "excluded_work_ids": excluded_work_ids
            if excluded_work_ids is not None
            else ["W2", "W1"],
        },
    }
    if display_name is not None:
        body["display_name"] = display_name
    return body


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


def test_same_authors_reordered_are_duplicates(tmp_path, monkeypatch):
    client, engine = _client(tmp_path, monkeypatch)
    try:
        first = client.post("/api/saved-searches", json=_author_payload(("c1", "c2")))
        second = client.post("/api/saved-searches", json=_author_payload(("c2", "c1")))

        assert first.status_code == 200
        assert second.status_code == 200
        assert first.json()["outcome"] == "created"
        assert second.json()["outcome"] == "already_exists"
        assert first.json()["id"] == second.json()["id"]
        assert first.json()["payload"]["analysis_mode"] == "common_publications"

        listing = client.get("/api/saved-searches", params={"type": "authors"})
        assert listing.status_code == 200
        assert len(listing.json()["items"]) == 1
    finally:
        app.dependency_overrides.clear()
        asyncio.run(engine.dispose())


def test_same_authors_same_filters_are_duplicates(tmp_path, monkeypatch):
    client, engine = _client(tmp_path, monkeypatch)
    try:
        first = client.post(
            "/api/saved-searches",
            json=_author_payload(display_name="Lab team"),
        )
        second = client.post(
            "/api/saved-searches",
            json=_author_payload(display_name="Different name"),
        )
        assert first.json()["id"] == second.json()["id"]
        assert second.json()["outcome"] == "already_exists"
        # Name does not determine identity and duplicate save must not overwrite.
        assert second.json()["display_name"] == "Lab team"
    finally:
        app.dependency_overrides.clear()
        asyncio.run(engine.dispose())


def test_same_authors_different_filters_allowed(tmp_path, monkeypatch):
    client, engine = _client(tmp_path, monkeypatch)
    try:
        one = client.post(
            "/api/saved-searches",
            json=_author_payload(filters={"from_year": 2020}),
        )
        two = client.post(
            "/api/saved-searches",
            json=_author_payload(filters={"from_year": 2021}),
        )
        assert one.status_code == 200
        assert two.status_code == 200
        assert one.json()["id"] != two.json()["id"]
        assert two.json()["outcome"] == "created"
    finally:
        app.dependency_overrides.clear()
        asyncio.run(engine.dispose())


def test_excluded_works_do_not_affect_identity(tmp_path, monkeypatch):
    client, engine = _client(tmp_path, monkeypatch)
    try:
        one = client.post(
            "/api/saved-searches",
            json=_author_payload(excluded_work_ids=["W1"]),
        )
        two = client.post(
            "/api/saved-searches",
            json=_author_payload(excluded_work_ids=["W9"]),
        )
        assert one.json()["id"] == two.json()["id"]
        assert two.json()["outcome"] == "already_exists"
    finally:
        app.dependency_overrides.clear()
        asyncio.run(engine.dispose())


def test_rename_keeps_same_saved_search(tmp_path, monkeypatch):
    client, engine = _client(tmp_path, monkeypatch)
    try:
        created = client.post("/api/saved-searches", json=_author_payload()).json()
        renamed = client.patch(
            f"/api/saved-searches/{created['id']}",
            json={"display_name": "Custom label"},
        )
        assert renamed.status_code == 200
        assert renamed.json()["id"] == created["id"]
        assert renamed.json()["canonical_key"] == created["canonical_key"]
        assert renamed.json()["display_name"] == "Custom label"
        assert renamed.json()["outcome"] == "updated"

        cleared = client.patch(
            f"/api/saved-searches/{created['id']}",
            json={"display_name": ""},
        )
        assert cleared.status_code == 200
        assert cleared.json()["canonical_key"] == created["canonical_key"]
        assert cleared.json()["display_name"] == "John Smith + Jane Doe"
    finally:
        app.dependency_overrides.clear()
        asyncio.run(engine.dispose())


def test_add_and_remove_author_via_patch(tmp_path, monkeypatch):
    client, engine = _client(tmp_path, monkeypatch)
    try:
        created = client.post(
            "/api/saved-searches",
            json=_author_payload(("c1", "c2")),
        ).json()
        assert created["payload"]["analysis_mode"] == "common_publications"

        removed = client.patch(
            f"/api/saved-searches/{created['id']}",
            json={
                "authors": [
                    {
                        "canonical_author_id": "c1",
                        "display_name": "John Smith",
                        "provider": "openalex",
                        "provider_author_id": "A1",
                    }
                ]
            },
        )
        assert removed.status_code == 200
        assert removed.json()["canonical_key"] != created["canonical_key"]
        assert removed.json()["payload"]["analysis_mode"] == "single_author"
        assert [a["canonical_author_id"] for a in removed.json()["payload"]["authors"]] == ["c1"]

        added = client.patch(
            f"/api/saved-searches/{created['id']}",
            json={
                "authors": [
                    {
                        "canonical_author_id": "c1",
                        "display_name": "John Smith",
                        "provider": "openalex",
                        "provider_author_id": "A1",
                    },
                    {
                        "canonical_author_id": "c3",
                        "display_name": "Alex Roe",
                        "provider": "openalex",
                        "provider_author_id": "A3",
                    },
                ]
            },
        )
        assert added.status_code == 200
        ids = [a["canonical_author_id"] for a in added.json()["payload"]["authors"]]
        assert ids == ["c1", "c3"]
    finally:
        app.dependency_overrides.clear()
        asyncio.run(engine.dispose())


def test_edit_into_existing_configuration_rejected(tmp_path, monkeypatch):
    client, engine = _client(tmp_path, monkeypatch)
    try:
        first = client.post(
            "/api/saved-searches",
            json=_author_payload(("c1", "c2"), filters={"from_year": 2020}),
        ).json()
        second = client.post(
            "/api/saved-searches",
            json=_author_payload(("c1", "c2"), filters={"from_year": 2021}),
        ).json()
        assert first["id"] != second["id"]

        conflict = client.patch(
            f"/api/saved-searches/{second['id']}",
            json={"filters": {"from_year": 2020}},
        )
        assert conflict.status_code == 409
        assert "already exists" in conflict.json()["detail"].lower()

        listing = client.get("/api/saved-searches", params={"type": "authors"})
        assert len(listing.json()["items"]) == 2
    finally:
        app.dependency_overrides.clear()
        asyncio.run(engine.dispose())


def test_lookup_and_delete_support_save_unsave(tmp_path, monkeypatch):
    client, engine = _client(tmp_path, monkeypatch)
    try:
        payload = _author_payload()
        missing = client.post("/api/saved-searches/lookup", json=payload)
        assert missing.status_code == 200
        assert missing.json()["item"] is None

        created = client.post("/api/saved-searches", json=payload).json()
        found = client.post("/api/saved-searches/lookup", json=payload)
        assert found.json()["item"]["id"] == created["id"]

        assert client.delete(f"/api/saved-searches/{created['id']}").status_code == 204
        after = client.post("/api/saved-searches/lookup", json=payload)
        assert after.json()["item"] is None
    finally:
        app.dependency_overrides.clear()
        asyncio.run(engine.dispose())


def test_list_search_by_name_and_author(tmp_path, monkeypatch):
    client, engine = _client(tmp_path, monkeypatch)
    try:
        client.post(
            "/api/saved-searches",
            json=_author_payload(("c1", "c2"), display_name="Berkeley lab"),
        )
        client.post(
            "/api/saved-searches",
            json=_author_payload(("c3",), filters={"from_year": 2019}, display_name="Solo"),
        )

        by_name = client.get("/api/saved-searches", params={"type": "authors", "q": "berkeley"})
        assert len(by_name.json()["items"]) == 1
        assert by_name.json()["items"][0]["display_name"] == "Berkeley lab"

        by_author = client.get("/api/saved-searches", params={"type": "authors", "q": "alex"})
        assert len(by_author.json()["items"]) == 1
        assert by_author.json()["items"][0]["display_name"] == "Solo"
    finally:
        app.dependency_overrides.clear()
        asyncio.run(engine.dispose())


def test_empty_custom_name_uses_author_label(tmp_path, monkeypatch):
    client, engine = _client(tmp_path, monkeypatch)
    try:
        created = client.post(
            "/api/saved-searches",
            json=_author_payload(display_name=""),
        )
        assert created.status_code == 200
        assert created.json()["display_name"] == "John Smith + Jane Doe"
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
        assert second.json()["outcome"] == "already_exists"
        assert second.json()["display_name"] == "R01 GM-123456"
        assert first.json()["metadata"] == {"funder_name": "NIH"}

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

    engine = create_async_engine(f"sqlite+aiosqlite:///{db_path}")

    async def check() -> None:
        async with engine.connect() as conn:
            result = await conn.execute(
                text(
                    "SELECT name FROM sqlite_master WHERE type='table' AND name='saved_searches'"
                )
            )
            assert result.scalar_one() == "saved_searches"

    try:
        asyncio.run(check())
    finally:
        asyncio.run(engine.dispose())
