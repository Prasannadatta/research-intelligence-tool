"""Analyze Authors full-corpus publication statistics jobs."""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, patch

import pytest
import pytest_asyncio
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from app.core.config import get_settings
from app.db.base import Base
from app.db.models import AuthorWorkSyncState, CanonicalAuthor, ProviderAuthorRecord
from app.db.session import get_db_session
from app.main import app
from app.services.analysis import publication_stats_jobs
from app.services.analysis.publication_stats_jobs import (
    reset_publication_stats_job_semaphore_for_tests,
    run_publication_stats_job,
)
from tests.test_author_insights import _author_payload, _seed_author, _seed_work
from tests.test_author_work_sync import _work_row

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
    reset_publication_stats_job_semaphore_for_tests()
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
        reset_publication_stats_job_semaphore_for_tests()
        await engine.dispose()


def _hold_scheduler(monkeypatch):
    scheduled: list[str] = []
    monkeypatch.setattr(publication_stats_jobs, "schedule_publication_stats_job", scheduled.append)
    return scheduled


async def _mark_complete(session: AsyncSession, author_id: uuid.UUID, *, stored: int = 1) -> None:
    now = datetime.now(timezone.utc)
    session.add(
        AuthorWorkSyncState(
            id=uuid.uuid4(),
            canonical_author_id=author_id,
            provider="openalex",
            last_synced_at=now,
            last_successful_synced_at=now,
            last_attempted_at=now,
            stored_work_count=stored,
            provider_work_count=stored,
            status="complete",
        )
    )


async def _set_works_count(session: AsyncSession, author: CanonicalAuthor, count: int) -> None:
    record = (
        await session.execute(
            select(ProviderAuthorRecord).where(
                ProviderAuthorRecord.canonical_author_id == author.id,
                ProviderAuthorRecord.provider == "openalex",
            )
        )
    ).scalar_one()
    record.works_count = count
    await session.commit()


@pytest.mark.asyncio
async def test_stats_job_syncs_then_returns_full_timeline_and_facets(session_factory, monkeypatch):
    _hold_scheduler(monkeypatch)
    monkeypatch.setattr(publication_stats_jobs, "SessionLocal", session_factory)

    async with session_factory() as session:
        author = await _seed_author(session, name="Stats Author", openalex_id="ST1")
        await _set_works_count(session, author, 2)

    with patch(
        "app.services.analysis.author_work_sync.search_works_by_author_ids",
        new_callable=AsyncMock,
        return_value={
            "results": [
                _work_row("ST-W1", "One", [("ST1", "Stats Author")]),
                _work_row("ST-W2", "Two", [("ST1", "Stats Author")]),
            ],
            "has_more": False,
            "next_cursor": None,
            "count": 2,
        },
    ) as mock_fetch:
        created = client.post(
            "/api/analysis/authors/publications/stats/jobs",
            json={"authors": [_author_payload(author.id, "Stats Author")]},
        )
        assert created.status_code == 200
        job_id = created.json()["job_id"]
        await run_publication_stats_job(job_id)

    done = client.get(f"/api/analysis/authors/publications/stats/jobs/{job_id}").json()
    assert done["status"] == "completed"
    assert done["result"]["corpus_complete"] is True
    assert done["result"]["total_matching_publications"] == 2
    assert len(done["result"]["timeline"]["items"]) >= 1
    assert isinstance(done["result"]["facets"]["sources"], list)
    assert mock_fetch.await_count == 1


@pytest.mark.asyncio
async def test_stats_job_skips_http_for_fresh_complete(session_factory, monkeypatch):
    _hold_scheduler(monkeypatch)
    monkeypatch.setattr(publication_stats_jobs, "SessionLocal", session_factory)

    async with session_factory() as session:
        author = await _seed_author(session, name="Fresh", openalex_id="FR1")
        await _seed_work(
            session,
            title="Stored",
            year=2022,
            provider_work_id="FRW1",
            selected_authors=[author],
        )
        await _mark_complete(session, author.id)
        await session.commit()

    with patch(
        "app.services.analysis.author_work_sync.search_works_by_author_ids",
        new_callable=AsyncMock,
    ) as mock_fetch:
        created = client.post(
            "/api/analysis/authors/publications/stats/jobs",
            json={"authors": [_author_payload(author.id, "Fresh")]},
        )
        job_id = created.json()["job_id"]
        await run_publication_stats_job(job_id)
        second = client.post(
            "/api/analysis/authors/publications/stats/jobs",
            json={"authors": [_author_payload(author.id, "Fresh")]},
        )
        job_id2 = second.json()["job_id"]
        await run_publication_stats_job(job_id2)

    assert mock_fetch.await_count == 0
    assert client.get(f"/api/analysis/authors/publications/stats/jobs/{job_id}").json()["status"] == "completed"
    assert client.get(f"/api/analysis/authors/publications/stats/jobs/{job_id2}").json()["status"] == "completed"


@pytest.mark.asyncio
async def test_stats_job_refreshes_stale_and_fails_on_provider_error(session_factory, monkeypatch):
    _hold_scheduler(monkeypatch)
    monkeypatch.setattr(publication_stats_jobs, "SessionLocal", session_factory)

    async with session_factory() as session:
        stale = await _seed_author(session, name="Stale", openalex_id="SL1")
        broken = await _seed_author(session, name="Broken", openalex_id="BR1")
        now = datetime.now(timezone.utc)
        session.add(
            AuthorWorkSyncState(
                id=uuid.uuid4(),
                canonical_author_id=stale.id,
                provider="openalex",
                last_synced_at=now - timedelta(days=4),
                last_successful_synced_at=now - timedelta(days=4),
                last_attempted_at=now - timedelta(days=4),
                stored_work_count=0,
                provider_work_count=1,
                status="complete",
            )
        )
        await session.commit()

    async def fake_fetch(*, author_id_groups, **_kwargs):
        author_id = author_id_groups[0][0]
        if author_id == "BR1":
            raise RuntimeError("provider down")
        return {
            "results": [_work_row("SL-W1", "Stale Paper", [("SL1", "Stale")])],
            "has_more": False,
            "next_cursor": None,
            "count": 1,
        }

    with patch(
        "app.services.analysis.author_work_sync.search_works_by_author_ids",
        side_effect=fake_fetch,
    ):
        created = client.post(
            "/api/analysis/authors/publications/stats/jobs",
            json={
                "authors": [
                    _author_payload(stale.id, "Stale"),
                    _author_payload(broken.id, "Broken"),
                ]
            },
        )
        job_id = created.json()["job_id"]
        await run_publication_stats_job(job_id)

    payload = client.get(f"/api/analysis/authors/publications/stats/jobs/{job_id}").json()
    assert payload["status"] == "failed"
    assert payload["result"] is None
    assert "incomplete" in (payload["error_message"] or "").lower() or "failed" in (
        payload["error_message"] or ""
    ).lower()


@pytest.mark.asyncio
async def test_stats_job_intersection_for_three_authors(session_factory, monkeypatch):
    _hold_scheduler(monkeypatch)
    monkeypatch.setattr(publication_stats_jobs, "SessionLocal", session_factory)

    async with session_factory() as session:
        a = await _seed_author(session, name="A", openalex_id="IA1")
        b = await _seed_author(session, name="B", openalex_id="IA2")
        c = await _seed_author(session, name="C", openalex_id="IA3")
        await _seed_work(
            session,
            title="ABC",
            year=2020,
            provider_work_id="IABC",
            selected_authors=[a, b, c],
        )
        await _seed_work(
            session,
            title="AB only",
            year=2021,
            provider_work_id="IAB",
            selected_authors=[a, b],
        )
        for author in (a, b, c):
            await _mark_complete(session, author.id, stored=2)
        await session.commit()

    with patch(
        "app.services.analysis.author_work_sync.search_works_by_author_ids",
        new_callable=AsyncMock,
    ) as mock_fetch:
        created = client.post(
            "/api/analysis/authors/publications/stats/jobs",
            json={
                "authors": [
                    _author_payload(a.id, "A"),
                    _author_payload(b.id, "B"),
                    _author_payload(c.id, "C"),
                ]
            },
        )
        job_id = created.json()["job_id"]
        await run_publication_stats_job(job_id)

    assert mock_fetch.await_count == 0
    payload = client.get(f"/api/analysis/authors/publications/stats/jobs/{job_id}").json()
    assert payload["status"] == "completed"
    assert payload["result"]["mode"] == "common_publications"
    assert payload["result"]["total_matching_publications"] == 1


@pytest.mark.asyncio
async def test_stats_job_rate_limit_preserves_incomplete_status(session_factory, monkeypatch):
    _hold_scheduler(monkeypatch)
    monkeypatch.setattr(publication_stats_jobs, "SessionLocal", session_factory)

    async with session_factory() as session:
        author = await _seed_author(session, name="Limited", openalex_id="RL1")
        await _set_works_count(session, author, 1)

    from app.integrations.openalex.client import OpenAlexApiError

    with patch(
        "app.services.analysis.author_work_sync.search_works_by_author_ids",
        new_callable=AsyncMock,
        side_effect=OpenAlexApiError("OpenAlex rate limit reached.", status_code=429),
    ):
        created = client.post(
            "/api/analysis/authors/publications/stats/jobs",
            json={"authors": [_author_payload(author.id, "Limited")]},
        )
        job_id = created.json()["job_id"]
        await run_publication_stats_job(job_id)

    payload = client.get(f"/api/analysis/authors/publications/stats/jobs/{job_id}").json()
    assert payload["status"] == "failed"
    assert payload["result"] is None
    assert payload["progress_detail"]["rate_limited"] is True
    assert payload["progress_detail"]["corpus_complete"] is False
    assert "rate limit reached" in (payload["error_message"] or "").lower()
    assert "existing data is safe" in (payload["error_message"] or "").lower()


@pytest.mark.asyncio
async def test_stats_job_fails_when_author_has_no_provider_identity(session_factory, monkeypatch):
    _hold_scheduler(monkeypatch)
    monkeypatch.setattr(publication_stats_jobs, "SessionLocal", session_factory)

    async with session_factory() as session:
        author = CanonicalAuthor(
            id=uuid.uuid4(),
            preferred_name="No Provider",
            normalized_name="no provider",
            resolution_status="merged",
        )
        session.add(author)
        await session.commit()
        author_id = author.id

    created = client.post(
        "/api/analysis/authors/publications/stats/jobs",
        json={"authors": [_author_payload(author_id, "No Provider")]},
    )
    job_id = created.json()["job_id"]
    await run_publication_stats_job(job_id)
    payload = client.get(f"/api/analysis/authors/publications/stats/jobs/{job_id}").json()
    assert payload["status"] == "failed"
    assert payload["result"] is None
    assert payload["progress_detail"]["corpus_complete"] is False
    assert "provider" in (payload["error_message"] or "").lower()
