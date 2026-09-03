"""Insights jobs synchronize author publications before building the dashboard."""

from __future__ import annotations

import asyncio
import time
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
from app.services.analysis import insights_jobs
from app.services.analysis.insights_jobs import (
    reset_insights_job_semaphore_for_tests,
    run_insights_job,
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
    reset_insights_job_semaphore_for_tests()
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
        reset_insights_job_semaphore_for_tests()
        await engine.dispose()


def _hold_scheduler(monkeypatch):
    scheduled: list[str] = []
    monkeypatch.setattr(insights_jobs, "schedule_insights_job", scheduled.append)
    return scheduled


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
async def test_insights_job_syncs_new_author_then_builds_dashboard(session_factory, monkeypatch):
    _hold_scheduler(monkeypatch)
    monkeypatch.setattr(insights_jobs, "SessionLocal", session_factory)

    async with session_factory() as session:
        author = await _seed_author(session, name="New Author", openalex_id="NA1")
        await _set_works_count(session, author, 1)

    with patch(
        "app.services.analysis.author_work_sync.search_works_by_author_ids",
        new_callable=AsyncMock,
        return_value={
            "results": [_work_row("NW1", "Fresh Paper", [("NA1", "New Author")])],
            "has_more": False,
            "next_cursor": None,
        },
    ) as mock_fetch:
        created = client.post(
            "/api/analysis/authors/insights/jobs",
            json={"authors": [_author_payload(author.id, "New Author")]},
        )
        assert created.status_code == 200
        job_id = created.json()["job_id"]
        await run_insights_job(job_id)

    done = client.get(f"/api/analysis/authors/insights/jobs/{job_id}")
    payload = done.json()
    assert payload["status"] == "completed"
    assert payload["result"]["metrics"]["total_unique_publications"] == 1
    assert payload["result"]["facets"] is not None
    assert mock_fetch.await_count == 1

    async with session_factory() as session:
        state = (
            await session.execute(
                select(AuthorWorkSyncState).where(
                    AuthorWorkSyncState.canonical_author_id == author.id
                )
            )
        ).scalar_one()
    assert state.status == "complete"


@pytest.mark.asyncio
async def test_insights_job_skips_provider_http_for_fresh_complete_author(
    session_factory, monkeypatch
):
    _hold_scheduler(monkeypatch)
    monkeypatch.setattr(insights_jobs, "SessionLocal", session_factory)

    async with session_factory() as session:
        author = await _seed_author(session, name="Fresh Author", openalex_id="FA1")
        await _seed_work(
            session,
            title="Already Stored",
            year=2024,
            provider_work_id="FW1",
            selected_authors=[author],
        )
        session.add(
            AuthorWorkSyncState(
                id=uuid.uuid4(),
                canonical_author_id=author.id,
                provider="openalex",
                last_synced_at=datetime.now(timezone.utc),
                last_successful_synced_at=datetime.now(timezone.utc),
                last_attempted_at=datetime.now(timezone.utc),
                stored_work_count=1,
                provider_work_count=1,
                status="complete",
            )
        )
        await session.commit()

    with patch(
        "app.services.analysis.author_work_sync.search_works_by_author_ids",
        new_callable=AsyncMock,
    ) as mock_fetch:
        first_started = time.perf_counter()
        created = client.post(
            "/api/analysis/authors/insights/jobs",
            json={"authors": [_author_payload(author.id, "Fresh Author")]},
        )
        job_id = created.json()["job_id"]
        await run_insights_job(job_id)
        first_ms = (time.perf_counter() - first_started) * 1000

        second_started = time.perf_counter()
        created2 = client.post(
            "/api/analysis/authors/insights/jobs",
            json={"authors": [_author_payload(author.id, "Fresh Author")]},
        )
        job_id2 = created2.json()["job_id"]
        await run_insights_job(job_id2)
        second_ms = (time.perf_counter() - second_started) * 1000

    assert mock_fetch.await_count == 0
    assert client.get(f"/api/analysis/authors/insights/jobs/{job_id}").json()["status"] == "completed"
    assert client.get(f"/api/analysis/authors/insights/jobs/{job_id2}").json()["status"] == "completed"
    assert first_ms < 2000
    assert second_ms < 2000


@pytest.mark.asyncio
async def test_insights_job_refreshes_stale_author(session_factory, monkeypatch):
    _hold_scheduler(monkeypatch)
    monkeypatch.setattr(insights_jobs, "SessionLocal", session_factory)

    async with session_factory() as session:
        author = await _seed_author(session, name="Stale Author", openalex_id="SA1")
        await _set_works_count(session, author, 1)
        session.add(
            AuthorWorkSyncState(
                id=uuid.uuid4(),
                canonical_author_id=author.id,
                provider="openalex",
                last_synced_at=datetime.now(timezone.utc) - timedelta(days=3),
                last_successful_synced_at=datetime.now(timezone.utc) - timedelta(days=3),
                last_attempted_at=datetime.now(timezone.utc) - timedelta(days=3),
                stored_work_count=0,
                provider_work_count=1,
                status="complete",
            )
        )
        await session.commit()

    with patch(
        "app.services.analysis.author_work_sync.search_works_by_author_ids",
        new_callable=AsyncMock,
        return_value={
            "results": [_work_row("SW1", "Refreshed", [("SA1", "Stale Author")])],
            "has_more": False,
            "next_cursor": None,
        },
    ) as mock_fetch:
        created = client.post(
            "/api/analysis/authors/insights/jobs",
            json={"authors": [_author_payload(author.id, "Stale Author")]},
        )
        job_id = created.json()["job_id"]
        await run_insights_job(job_id)

    assert mock_fetch.await_count == 1
    payload = client.get(f"/api/analysis/authors/insights/jobs/{job_id}").json()
    assert payload["status"] == "completed"
    assert payload["result"]["metrics"]["total_unique_publications"] == 1

    async with session_factory() as session:
        state = (
            await session.execute(
                select(AuthorWorkSyncState).where(
                    AuthorWorkSyncState.canonical_author_id == author.id
                )
            )
        ).scalar_one()
    assert state.status == "complete"


@pytest.mark.asyncio
async def test_partial_sync_is_retried_and_not_treated_as_complete(session_factory, monkeypatch):
    _hold_scheduler(monkeypatch)
    monkeypatch.setattr(insights_jobs, "SessionLocal", session_factory)

    async with session_factory() as session:
        author = await _seed_author(session, name="Partial Author", openalex_id="PA1")
        await _set_works_count(session, author, 2)
        session.add(
            AuthorWorkSyncState(
                id=uuid.uuid4(),
                canonical_author_id=author.id,
                provider="openalex",
                last_synced_at=datetime.now(timezone.utc),
                last_successful_synced_at=None,
                last_attempted_at=datetime.now(timezone.utc),
                stored_work_count=1,
                provider_work_count=2,
                status="partial",
                error_message="Timed out earlier",
            )
        )
        await session.commit()

    with patch(
        "app.services.analysis.author_work_sync.search_works_by_author_ids",
        new_callable=AsyncMock,
        return_value={
            "results": [
                _work_row("PW1", "One", [("PA1", "Partial Author")]),
                _work_row("PW2", "Two", [("PA1", "Partial Author")]),
            ],
            "has_more": False,
            "next_cursor": None,
        },
    ) as mock_fetch:
        created = client.post(
            "/api/analysis/authors/insights/jobs",
            json={"authors": [_author_payload(author.id, "Partial Author")]},
        )
        job_id = created.json()["job_id"]
        await run_insights_job(job_id)

    assert mock_fetch.await_count == 1
    payload = client.get(f"/api/analysis/authors/insights/jobs/{job_id}").json()
    assert payload["status"] == "completed"


@pytest.mark.asyncio
async def test_provider_failure_fails_insights_job_without_dashboard(session_factory, monkeypatch):
    _hold_scheduler(monkeypatch)
    monkeypatch.setattr(insights_jobs, "SessionLocal", session_factory)

    async with session_factory() as session:
        author = await _seed_author(session, name="Broken Author", openalex_id="BA1")
        await session.commit()

    with patch(
        "app.services.analysis.author_work_sync.search_works_by_author_ids",
        new_callable=AsyncMock,
        side_effect=RuntimeError("OpenAlex down"),
    ):
        created = client.post(
            "/api/analysis/authors/insights/jobs",
            json={"authors": [_author_payload(author.id, "Broken Author")]},
        )
        job_id = created.json()["job_id"]
        await run_insights_job(job_id)

    payload = client.get(f"/api/analysis/authors/insights/jobs/{job_id}").json()
    assert payload["status"] == "failed"
    assert payload["result"] is None
    assert "incomplete" in (payload["error_message"] or "").lower() or "failed" in (
        payload["error_message"] or ""
    ).lower()


@pytest.mark.asyncio
async def test_mixed_fresh_and_stale_authors(session_factory, monkeypatch):
    _hold_scheduler(monkeypatch)
    monkeypatch.setattr(insights_jobs, "SessionLocal", session_factory)

    async with session_factory() as session:
        fresh = await _seed_author(session, name="Fresh", openalex_id="MX1")
        stale = await _seed_author(session, name="Stale", openalex_id="MX2")
        missing = await _seed_author(session, name="Missing", openalex_id="MX3")
        await _seed_work(
            session,
            title="Fresh Paper",
            year=2024,
            provider_work_id="MXW1",
            selected_authors=[fresh],
        )
        now = datetime.now(timezone.utc)
        session.add(
            AuthorWorkSyncState(
                id=uuid.uuid4(),
                canonical_author_id=fresh.id,
                provider="openalex",
                last_synced_at=now,
                last_successful_synced_at=now,
                last_attempted_at=now,
                stored_work_count=1,
                provider_work_count=1,
                status="complete",
            )
        )
        session.add(
            AuthorWorkSyncState(
                id=uuid.uuid4(),
                canonical_author_id=stale.id,
                provider="openalex",
                last_synced_at=now - timedelta(days=5),
                last_successful_synced_at=now - timedelta(days=5),
                last_attempted_at=now - timedelta(days=5),
                stored_work_count=0,
                provider_work_count=1,
                status="complete",
            )
        )
        await session.commit()

    async def fake_fetch(*, author_id_groups, **_kwargs):
        author_id = author_id_groups[0][0]
        return {
            "results": [_work_row(f"W-{author_id}", f"Paper {author_id}", [(author_id, "X")])],
            "has_more": False,
            "next_cursor": None,
        }

    with patch(
        "app.services.analysis.author_work_sync.search_works_by_author_ids",
        side_effect=fake_fetch,
    ) as mock_fetch:
        created = client.post(
            "/api/analysis/authors/insights/jobs",
            json={
                "authors": [
                    _author_payload(fresh.id, "Fresh"),
                    _author_payload(stale.id, "Stale"),
                    _author_payload(missing.id, "Missing"),
                ]
            },
        )
        job_id = created.json()["job_id"]
        await run_insights_job(job_id)

    # Fresh skipped; stale + missing fetched.
    assert mock_fetch.await_count == 2
    payload = client.get(f"/api/analysis/authors/insights/jobs/{job_id}").json()
    assert payload["status"] == "completed"
    assert payload["result"]["metrics"]["total_unique_publications"] >= 3


@pytest.mark.asyncio
async def test_insights_job_progress_includes_author_and_counts(session_factory, monkeypatch):
    _hold_scheduler(monkeypatch)
    monkeypatch.setattr(insights_jobs, "SessionLocal", session_factory)
    progress_events: list[dict] = []

    async with session_factory() as session:
        author = await _seed_author(session, name="Martin Head-Gordon", openalex_id="MHG1")
        await _set_works_count(session, author, 2)

    pages = [
        {
            "results": [_work_row("MHG-W1", "One", [("MHG1", "Martin Head-Gordon")])],
            "has_more": True,
            "next_cursor": "c2",
        },
        {
            "results": [_work_row("MHG-W2", "Two", [("MHG1", "Martin Head-Gordon")])],
            "has_more": False,
            "next_cursor": None,
        },
    ]

    with patch(
        "app.services.analysis.author_work_sync.search_works_by_author_ids",
        new_callable=AsyncMock,
        side_effect=pages,
    ):
        created = client.post(
            "/api/analysis/authors/insights/jobs",
            json={"authors": [_author_payload(author.id, "Martin Head-Gordon")]},
        )
        job_id = created.json()["job_id"]

        async def run_and_sample():
            task = asyncio.create_task(run_insights_job(job_id))
            for _ in range(40):
                await asyncio.sleep(0.01)
                row = client.get(f"/api/analysis/authors/insights/jobs/{job_id}").json()
                progress_events.append(
                    {
                        "stage": row.get("progress_stage"),
                        "detail": row.get("progress_detail"),
                        "status": row.get("status"),
                    }
                )
                if row.get("status") in {"completed", "failed"}:
                    break
            await task

        await run_and_sample()

    done = client.get(f"/api/analysis/authors/insights/jobs/{job_id}").json()
    assert done["status"] == "completed"
    sync_stages = [
        event
        for event in progress_events
        if event.get("detail") and event["detail"].get("author_name")
    ]
    assert sync_stages
    assert any(
        "Martin Head-Gordon" in str(event.get("stage") or "")
        or event["detail"].get("author_name") == "Martin Head-Gordon"
        for event in sync_stages
    )
