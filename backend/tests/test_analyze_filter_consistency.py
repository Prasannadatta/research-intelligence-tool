"""Table and stats must share stored-corpus filter rules when coverage is verified."""

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
from app.services.analysis import publication_stats_jobs
from app.services.analysis.publication_stats_jobs import (
    reset_publication_stats_job_semaphore_for_tests,
    run_publication_stats_job,
)
from tests.test_author_insights import _author_payload, _seed_author, _seed_work

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


@pytest.mark.asyncio
async def test_year_filter_table_and_stats_use_same_stored_corpus(session_factory, monkeypatch):
    monkeypatch.setattr(publication_stats_jobs, "schedule_publication_stats_job", lambda *_: None)
    monkeypatch.setattr(publication_stats_jobs, "SessionLocal", session_factory)

    async with session_factory() as session:
        author = await _seed_author(session, name="Filter Author", openalex_id="FA1")
        await _seed_work(
            session,
            title="Old Paper",
            year=2018,
            provider_work_id="OLD1",
            selected_authors=[author],
        )
        await _seed_work(
            session,
            title="New Paper",
            year=2023,
            provider_work_id="NEW1",
            selected_authors=[author],
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
                stored_work_count=2,
                provider_work_count=2,
                status="complete",
            )
        )
        await session.commit()
        author_id = author.id

    filters = {"from_year": 2020, "to_year": 2026}
    authors = [
        {
            "canonical_author_id": str(author_id),
            "display_name": "Filter Author",
            "provider": "openalex",
            "provider_author_id": "FA1",
        }
    ]

    with patch(
        "app.services.analysis.author_publications.search_works_by_author_ids",
        new_callable=AsyncMock,
    ) as mock_live:
        table = client.post(
            "/api/analysis/authors/publications",
            json={"authors": authors, "filters": filters, "limit": 20},
        )
        created = client.post(
            "/api/analysis/authors/publications/stats/jobs",
            json={"authors": [_author_payload(author_id, "Filter Author")], "filters": filters},
        )
        job_id = created.json()["job_id"]
        await run_publication_stats_job(job_id)

    assert table.status_code == 200
    table_body = table.json()
    assert [row["title"] for row in table_body["items"]] == ["New Paper"]
    # Verified corpus path — no live OpenAlex page crawl for the table.
    assert mock_live.await_count == 0

    stats = client.get(f"/api/analysis/authors/publications/stats/jobs/{job_id}").json()
    assert stats["status"] == "completed"
    assert stats["result"]["total_matching_publications"] == 1
    assert stats["result"]["timeline"]["total_matching_publications"] == 1


async def _seed_verified_author_with_years(session, *, years: list[int]):
    author = await _seed_author(session, name="Page Author", openalex_id="PA1")
    for index, year in enumerate(years):
        await _seed_work(
            session,
            title=f"Paper {year}-{index}",
            year=year,
            provider_work_id=f"W{year}{index}",
            selected_authors=[author],
            citation_count=index + 1,
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
            stored_work_count=len(years),
            provider_work_count=len(years),
            status="complete",
        )
    )
    await session.commit()
    return author


@pytest.mark.asyncio
async def test_verified_corpus_pagination_sort_filter_without_provider_calls(
    session_factory, monkeypatch
):
    monkeypatch.setattr(publication_stats_jobs, "schedule_publication_stats_job", lambda *_: None)
    monkeypatch.setattr(publication_stats_jobs, "SessionLocal", session_factory)

    years = [2020, 2021, 2022, 2023, 2024, 2025, 2025, 2019]
    async with session_factory() as session:
        author = await _seed_verified_author_with_years(session, years=years)
        author_id = author.id

    authors = [
        {
            "canonical_author_id": str(author_id),
            "display_name": "Page Author",
            "provider": "openalex",
            "provider_author_id": "PA1",
        }
    ]

    with patch(
        "app.services.analysis.author_publications.search_works_by_author_ids",
        new_callable=AsyncMock,
    ) as mock_live:
        page1 = client.post(
            "/api/analysis/authors/publications",
            json={
                "authors": authors,
                "limit": 3,
                "page": 1,
                "sort_by": "year",
                "sort_direction": "desc",
            },
        )
        page2 = client.post(
            "/api/analysis/authors/publications",
            json={
                "authors": authors,
                "limit": 3,
                "page": 2,
                "sort_by": "year",
                "sort_direction": "desc",
            },
        )
        filtered = client.post(
            "/api/analysis/authors/publications",
            json={
                "authors": authors,
                "limit": 20,
                "page": 1,
                "filters": {"from_year": 2025, "to_year": 2025},
                "sort_by": "year",
                "sort_direction": "desc",
            },
        )
        sorted_citations = client.post(
            "/api/analysis/authors/publications",
            json={
                "authors": authors,
                "limit": 20,
                "page": 1,
                "sort_by": "citations",
                "sort_direction": "desc",
            },
        )

    assert page1.status_code == 200
    assert page2.status_code == 200
    assert filtered.status_code == 200
    assert sorted_citations.status_code == 200
    assert mock_live.await_count == 0

    body1 = page1.json()
    body2 = page2.json()
    assert body1["pagination"]["corpus_source"] == "stored_complete_corpus"
    assert body1["pagination"]["total"] == 8
    assert body1["pagination"]["page"] == 1
    assert body1["pagination"]["offset"] == 0
    assert body1["pagination"]["has_more"] is True
    assert len(body1["items"]) == 3
    assert body2["pagination"]["page"] == 2
    assert body2["pagination"]["offset"] == 3
    assert [row["title"] for row in body1["items"]] != [row["title"] for row in body2["items"]]

    filtered_body = filtered.json()
    assert filtered_body["pagination"]["total"] == 2
    assert all(row["publication_year"] == 2025 for row in filtered_body["items"])

    cites = [
        row.get("citation_count") or row.get("cited_by_count") or 0
        for row in sorted_citations.json()["items"]
    ]
    assert cites == sorted(cites, reverse=True)


@pytest.mark.asyncio
async def test_2025_graph_and_table_counts_match_on_verified_corpus(
    session_factory, monkeypatch
):
    monkeypatch.setattr(publication_stats_jobs, "schedule_publication_stats_job", lambda *_: None)
    monkeypatch.setattr(publication_stats_jobs, "SessionLocal", session_factory)

    async with session_factory() as session:
        author = await _seed_verified_author_with_years(
            session,
            years=[2024, 2025, 2025, 2025, 2023],
        )
        author_id = author.id

    authors = [
        {
            "canonical_author_id": str(author_id),
            "display_name": "Page Author",
            "provider": "openalex",
            "provider_author_id": "PA1",
        }
    ]
    filters = {"from_year": 2025, "to_year": 2025}

    with patch(
        "app.services.analysis.author_publications.search_works_by_author_ids",
        new_callable=AsyncMock,
    ) as mock_live:
        table = client.post(
            "/api/analysis/authors/publications",
            json={"authors": authors, "filters": filters, "limit": 20, "page": 1},
        )
        created = client.post(
            "/api/analysis/authors/publications/stats/jobs",
            json={
                "authors": [_author_payload(author_id, "Page Author")],
                "filters": filters,
            },
        )
        job_id = created.json()["job_id"]
        await run_publication_stats_job(job_id)

    assert mock_live.await_count == 0
    table_body = table.json()
    assert table_body["pagination"]["total"] == 3
    assert len(table_body["items"]) == 3
    assert all(row["publication_year"] == 2025 for row in table_body["items"])

    stats = client.get(f"/api/analysis/authors/publications/stats/jobs/{job_id}").json()
    assert stats["status"] == "completed"
    assert stats["result"]["total_matching_publications"] == 3
    assert stats["result"]["timeline"]["total_matching_publications"] == 3
    year_buckets = {
        item["period"]: item["count"]
        for item in stats["result"]["timeline"]["items"]
    }
    assert year_buckets.get("2025") == 3
