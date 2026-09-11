"""Venue/grant facet suggestions prefer the stored verified corpus."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from unittest.mock import AsyncMock, patch

import pytest
import pytest_asyncio
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from app.core.config import get_settings
from app.db.base import Base
from app.db.models import AuthorWorkSyncState
from app.db.session import get_db_session
from app.main import app
from tests.test_author_insights import _seed_author, _seed_work

client = TestClient(app)


@pytest.fixture(autouse=True)
def _settings(monkeypatch):
    monkeypatch.setenv("OPENALEX_API_KEY", "test-key")
    monkeypatch.setenv("ARXIV_ENABLED", "false")
    monkeypatch.setenv("AUTHOR_WORK_SYNC_TTL_SECONDS", str(18 * 60 * 60))
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


@pytest_asyncio.fixture
async def session_factory():
    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)

    async def override_db():
        async with factory() as session:
            yield session

    app.dependency_overrides[get_db_session] = override_db
    try:
        yield factory
    finally:
        app.dependency_overrides.pop(get_db_session, None)
        await engine.dispose()


@pytest.mark.asyncio
async def test_venue_search_uses_stored_corpus_when_verified(session_factory):
    async with session_factory() as session:
        author = await _seed_author(session, name="Venue Author", openalex_id="VA1")
        await _seed_work(
            session,
            title="Stored Venue Paper",
            year=2022,
            provider_work_id="VW1",
            selected_authors=[author],
            venue="Nature Photonics",
        )
        now = datetime.now(timezone.utc)
        session.add(
            AuthorWorkSyncState(
                id=uuid.uuid4(),
                canonical_author_id=author.id,
                provider="openalex",
                last_synced_at=now,
                last_successful_synced_at=now,
                last_attempted_at=now,
                stored_work_count=1,
                provider_work_count=1,
                status="complete",
            )
        )
        await session.commit()
        author_id = author.id

    with patch(
        "app.services.analysis.author_publications.search_works_by_author_ids",
        new_callable=AsyncMock,
    ) as mock_fetch:
        response = client.post(
            "/api/analysis/authors/publications/venues/search",
            json={
                "authors": [
                    {
                        "canonical_author_id": str(author_id),
                        "display_name": "Venue Author",
                        "provider": "openalex",
                        "provider_author_id": "VA1",
                    }
                ],
                "query": "Nature",
                "limit": 10,
            },
        )

    assert response.status_code == 200
    rows = response.json()
    assert any(
        "nature" in str(row.get("label") or row.get("value") or "").lower()
        for row in rows
    )
    assert mock_fetch.await_count == 0
