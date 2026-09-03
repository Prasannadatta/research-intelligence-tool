"""Background Collaboration Insights job API."""

from __future__ import annotations

import asyncio
import time
import uuid
from datetime import datetime, timezone
from unittest.mock import patch

import pytest
import pytest_asyncio
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from app.db.base import Base
from app.db.models import AuthorWorkSyncState
from app.db.session import get_db_session
from app.main import app
from app.services.analysis import insights_jobs
from app.services.analysis.author_insights import AuthorInsightsService
from app.services.analysis.insights_jobs import (
    InsightsJobService,
    reset_insights_job_semaphore_for_tests,
    run_insights_job,
)
from tests.test_author_insights import (
    _author_payload,
    _seed_author,
    _seed_scalable_author_set,
    _seed_work,
)

client = TestClient(app)


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


@pytest.mark.asyncio
async def test_insights_job_post_returns_quickly_and_completes(session_factory, monkeypatch):
    scheduled = _hold_scheduler(monkeypatch)
    monkeypatch.setattr(insights_jobs, "SessionLocal", session_factory)

    async with session_factory() as session:
        author = await _seed_author(session, name="Job Author", openalex_id="JA1")
        await _seed_work(
            session,
            title="Job Paper",
            year=2024,
            provider_work_id="JW1",
            selected_authors=[author],
        )
        await _mark_complete(session, author.id)
        await session.commit()

    started = time.perf_counter()
    created = client.post(
        "/api/analysis/authors/insights/jobs",
        json={"authors": [_author_payload(author.id, "Job Author")]},
    )
    elapsed_ms = (time.perf_counter() - started) * 1000

    assert created.status_code == 200
    assert elapsed_ms < 500
    body = created.json()
    assert body["status"] == "queued"
    assert body["result"] is None
    assert body["progress_stage"] == "Preparing"
    job_id = body["job_id"]
    assert scheduled == [job_id]

    queued = client.get(f"/api/analysis/authors/insights/jobs/{job_id}")
    assert queued.status_code == 200
    assert queued.json()["status"] == "queued"

    await run_insights_job(job_id)

    done = client.get(f"/api/analysis/authors/insights/jobs/{job_id}")
    payload = done.json()
    assert payload["status"] == "completed"
    assert payload["progress_percent"] == 100
    assert payload["progress_stage"] == "Completed"
    assert payload["error_message"] is None
    assert payload["result"]["authors"][0]["display_name"] == "Job Author"
    assert payload["result"]["metrics"]["total_unique_publications"] == 1
    assert payload["started_at"] is not None
    assert payload["completed_at"] is not None


@pytest.mark.asyncio
async def test_insights_job_failure_is_stored_as_failed(session_factory, monkeypatch):
    _hold_scheduler(monkeypatch)
    monkeypatch.setattr(insights_jobs, "SessionLocal", session_factory)
    missing = uuid.uuid4()

    created = client.post(
        "/api/analysis/authors/insights/jobs",
        json={"authors": [_author_payload(missing, "Missing")]},
    )
    assert created.status_code == 200
    job_id = created.json()["job_id"]

    await run_insights_job(job_id)

    done = client.get(f"/api/analysis/authors/insights/jobs/{job_id}")
    payload = done.json()
    assert payload["status"] == "failed"
    assert payload["result"] is None
    assert "Canonical author not found" in (payload["error_message"] or "")
    assert payload["progress_stage"] == "Failed"
    assert payload["completed_at"] is not None


@pytest.mark.asyncio
async def test_insights_job_unexpected_error_does_not_hang(session_factory, monkeypatch):
    _hold_scheduler(monkeypatch)
    monkeypatch.setattr(insights_jobs, "SessionLocal", session_factory)

    async with session_factory() as session:
        author = await _seed_author(session, name="Boom Author", openalex_id="BA1")
        await _mark_complete(session, author.id, stored=0)
        await session.commit()

    async def boom(*_args, **_kwargs):
        raise RuntimeError("boom")

    created = client.post(
        "/api/analysis/authors/insights/jobs",
        json={"authors": [_author_payload(author.id, "Boom Author")]},
    )
    job_id = created.json()["job_id"]

    with patch.object(AuthorInsightsService, "build_dashboard", side_effect=boom):
        await run_insights_job(job_id)

    done = client.get(f"/api/analysis/authors/insights/jobs/{job_id}")
    payload = done.json()
    assert payload["status"] == "failed"
    assert payload["error_message"] == "Collaboration Insights job failed."
    assert payload["result"] is None


@pytest.mark.asyncio
async def test_fifty_author_insights_job_completes(session_factory, monkeypatch):
    _hold_scheduler(monkeypatch)
    monkeypatch.setattr(insights_jobs, "SessionLocal", session_factory)

    async with session_factory() as session:
        authors = await _seed_scalable_author_set(session, 50)
        for author in authors:
            await _mark_complete(session, author.id, stored=1)
        await session.commit()

    created = client.post(
        "/api/analysis/authors/insights/jobs",
        json={
            "authors": [
                _author_payload(author.id, author.preferred_name) for author in authors
            ]
        },
    )
    assert created.status_code == 200
    job_id = created.json()["job_id"]
    assert created.json()["status"] == "queued"

    await run_insights_job(job_id)

    done = client.get(f"/api/analysis/authors/insights/jobs/{job_id}")
    payload = done.json()
    assert payload["status"] == "completed"
    assert payload["result"]["combination_mode"] == "scalable"
    assert len(payload["result"]["combinations"]) == (50 * 49 // 2) + 1 + 1
    assert payload["progress_percent"] == 100


@pytest.mark.asyncio
async def test_insights_job_not_found(session_factory):
    missing = uuid.uuid4()
    response = client.get(f"/api/analysis/authors/insights/jobs/{missing}")
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_insights_jobs_limit_concurrency(monkeypatch):
    reset_insights_job_semaphore_for_tests()
    current = 0
    peak = 0

    class DummySession:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            return False

    async def fake_execute(self, job_id: str) -> None:
        nonlocal current, peak
        current += 1
        peak = max(peak, current)
        await asyncio.sleep(0.05)
        current -= 1

    monkeypatch.setattr(insights_jobs, "SessionLocal", DummySession)
    monkeypatch.setattr(InsightsJobService, "execute", fake_execute)

    await asyncio.gather(
        run_insights_job("1"),
        run_insights_job("2"),
        run_insights_job("3"),
    )
    assert peak <= 2
    reset_insights_job_semaphore_for_tests()
