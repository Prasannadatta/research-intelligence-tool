"""Regression: Insights + CSV share the verified stored corpus and source-aware enrichment."""

from __future__ import annotations

import csv
import io
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
from app.db.models import AuthorWorkSyncState, ProviderWorkRecord
from app.db.session import get_db_session
from app.main import app
from app.services.analysis import insights_jobs, publication_stats_jobs
from app.services.analysis.insights_jobs import run_insights_job
from app.services.analysis.publication_csv_export import publication_item_to_row_dict
from app.services.analysis.publication_stats_jobs import run_publication_stats_job
from tests.test_author_insights import _author_payload, _seed_author, _seed_work

client = TestClient(app)


@pytest.fixture(autouse=True)
def _settings(monkeypatch):
    monkeypatch.setenv("OPENALEX_API_KEY", "test-key")
    monkeypatch.setenv("ARXIV_ENABLED", "false")
    monkeypatch.setenv("AUTHOR_WORK_SYNC_TTL_SECONDS", str(18 * 60 * 60))
    monkeypatch.setenv("PUBLICATION_ENRICHMENT_ENABLED", "false")
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


@pytest_asyncio.fixture
async def session_factory():
    insights_jobs.reset_insights_job_semaphore_for_tests()
    publication_stats_jobs.reset_publication_stats_job_semaphore_for_tests()
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
        insights_jobs.reset_insights_job_semaphore_for_tests()
        publication_stats_jobs.reset_publication_stats_job_semaphore_for_tests()
        await engine.dispose()


async def _mark_verified(session: AsyncSession, author_id: uuid.UUID, *, work_count: int) -> None:
    now = datetime.now(timezone.utc)
    session.add(
        AuthorWorkSyncState(
            id=uuid.uuid4(),
            canonical_author_id=author_id,
            provider="openalex",
            last_synced_at=now,
            last_successful_synced_at=now,
            last_attempted_at=now,
            stored_work_count=work_count,
            provider_work_count=work_count,
            status="complete",
        )
    )
    await session.commit()


def _parse_csv(response):
    assert response.status_code == 200
    text = response.content.decode("utf-8-sig")
    rows = list(csv.reader(io.StringIO(text)))
    return rows[0], rows[1:]


@pytest.mark.asyncio
async def test_csv_uses_verified_stored_corpus_not_live_crawl(session_factory, monkeypatch):
    monkeypatch.setattr(publication_stats_jobs, "schedule_publication_stats_job", lambda *_: None)
    monkeypatch.setattr(publication_stats_jobs, "SessionLocal", session_factory)

    async with session_factory() as session:
        author = await _seed_author(session, name="Alp Sipahigil", openalex_id="AALP1")
        await _seed_work(
            session,
            title="Stored Paper 2019",
            year=2019,
            provider_work_id="WOLD",
            selected_authors=[author],
        )
        await _seed_work(
            session,
            title="Stored Paper 2023",
            year=2023,
            provider_work_id="WNEW",
            selected_authors=[author],
            citation_count=11,
        )
        await _mark_verified(session, author.id, work_count=2)
        author_id = author.id

    authors = [
        {
            "canonical_author_id": str(author_id),
            "display_name": "Alp Sipahigil",
            "provider": "openalex",
            "provider_author_id": "AALP1",
        }
    ]
    filters = {"from_year": 2020, "to_year": 2026}

    with patch(
        "app.services.analysis.author_publications.search_works_by_author_ids",
        new_callable=AsyncMock,
    ) as mock_live:
        table = client.post(
            "/api/analysis/authors/publications",
            json={"authors": authors, "filters": filters, "limit": 20},
        )
        export = client.post(
            "/api/analysis/authors/publications/export",
            json={"authors": authors, "filters": filters},
        )
        stats_job = client.post(
            "/api/analysis/authors/publications/stats/jobs",
            json={"authors": [_author_payload(author_id, "Alp Sipahigil")], "filters": filters},
        )
        await run_publication_stats_job(stats_job.json()["job_id"])

    assert mock_live.await_count == 0
    assert table.status_code == 200
    assert [row["title"] for row in table.json()["items"]] == ["Stored Paper 2023"]
    assert export.headers.get("x-corpus-source") == "stored_complete_corpus"

    header, rows = _parse_csv(export)
    assert [row[header.index("Title")] for row in rows] == ["Stored Paper 2023"]
    assert len(rows) == 1

    stats = client.get(
        f"/api/analysis/authors/publications/stats/jobs/{stats_job.json()['job_id']}"
    ).json()
    assert stats["status"] == "completed"
    assert stats["result"]["corpus_complete"] is True
    assert stats["result"]["total_matching_publications"] == 1
    assert stats["result"]["enrichment"] is not None
    assert stats["result"]["coverage"]["enrichment_affects_completeness"] is False


@pytest.mark.asyncio
async def test_common_publications_csv_matches_intersection(session_factory):
    async with session_factory() as session:
        monika = await _seed_author(
            session, name="Monika Schleier-Smith", openalex_id="AMSS1"
        )
        lin = await _seed_author(session, name="Lin Lin", openalex_id="ALL1")
        await _seed_work(
            session,
            title="Shared Only",
            year=2022,
            provider_work_id="WSHARED",
            selected_authors=[monika, lin],
        )
        await _seed_work(
            session,
            title="Monika Only",
            year=2022,
            provider_work_id="WAONLY",
            selected_authors=[monika],
        )
        await _mark_verified(session, monika.id, work_count=2)
        await _mark_verified(session, lin.id, work_count=1)
        monika_id = monika.id
        lin_id = lin.id

    payload_authors = [
        {
            "canonical_author_id": str(monika_id),
            "display_name": "Monika Schleier-Smith",
            "provider": "openalex",
            "provider_author_id": "AMSS1",
        },
        {
            "canonical_author_id": str(lin_id),
            "display_name": "Lin Lin",
            "provider": "openalex",
            "provider_author_id": "ALL1",
        },
    ]
    with patch(
        "app.services.analysis.author_publications.search_works_by_author_ids",
        new_callable=AsyncMock,
    ) as mock_live:
        export = client.post(
            "/api/analysis/authors/publications/export",
            json={"authors": payload_authors},
        )
    assert mock_live.await_count == 0
    header, rows = _parse_csv(export)
    assert [row[header.index("Title")] for row in rows] == ["Shared Only"]
    assert "common-publications" in export.headers["content-disposition"]


@pytest.mark.asyncio
async def test_insights_job_keeps_enrichment_and_uses_stored_corpus(session_factory, monkeypatch):
    monkeypatch.setattr(insights_jobs, "schedule_insights_job", lambda *_: None)
    monkeypatch.setattr(insights_jobs, "SessionLocal", session_factory)

    async with session_factory() as session:
        author = await _seed_author(session, name="Lin Lin", openalex_id="ALLIN1")
        work = await _seed_work(
            session,
            title="Insights Paper",
            year=2021,
            provider_work_id="WINS1",
            selected_authors=[author],
            citation_count=5,
            grant_number="R01GM111",
        )
        session.add(
            ProviderWorkRecord(
                id=uuid.uuid4(),
                canonical_work_id=work.id,
                provider="scopus",
                provider_work_id="851999",
                raw_metadata={
                    "citation_count": 99,
                    "scopus_id": "851999",
                    "journal": "Scopus Venue Should Not Win",
                },
            )
        )
        session.add(
            ProviderWorkRecord(
                id=uuid.uuid4(),
                canonical_work_id=work.id,
                provider="arxiv",
                provider_work_id="2101.12345",
                raw_metadata={
                    "arxiv_id": "2101.12345",
                    "arxiv_version": "2",
                    "work_type": "preprint",
                },
            )
        )
        await _mark_verified(session, author.id, work_count=1)
        author_id = author.id

    created = client.post(
        "/api/analysis/authors/insights/jobs",
        json={"authors": [_author_payload(author_id, "Lin Lin")]},
    )
    assert created.status_code == 200
    job_id = created.json()["job_id"]
    await run_insights_job(job_id)
    job = client.get(f"/api/analysis/authors/insights/jobs/{job_id}").json()
    assert job["status"] == "completed"
    result = job["result"]
    assert result["coverage"]["corpus_complete"] is True
    assert result["coverage"]["source"] == "stored_complete_corpus"
    assert result["coverage"]["enrichment_affects_completeness"] is False
    assert result["enrichment"] is not None
    assert result["metrics"]["total_unique_publications"] == 1
    # Preferred citation is OpenAlex, never summed/maxed with Scopus.
    assert result["metrics"]["total_citations"] == 5

    pubs = client.post(
        "/api/analysis/authors/insights/publications",
        json={
            "authors": [_author_payload(author_id, "Lin Lin")],
            "combination_id": str(author_id),
        },
    )
    assert pubs.status_code == 200
    item = pubs.json()["items"][0]
    assert item["citations_by_provider"]["openalex"] == 5
    assert item["citations_by_provider"]["scopus"] == 99
    assert item["citation_count"] == 5
    assert item["arxiv_id"] == "2101.12345"
    assert item["arxiv_version"] == "2"
    assert item["scopus_id"] == "851999"
    assert "arxiv" in item["providers"]
    assert "scopus" in item["providers"]


def test_csv_row_keeps_source_aware_citations_and_grants():
    row = publication_item_to_row_dict(
        {
            "title": "Enriched",
            "authors": [{"name": "Ada"}],
            "providers": ["openalex"],
            "url": "https://example.com",
            "journal": "Nature",
            "publication_date": "2024-01-01",
            "citation_count": 10,
            "citations_by_provider": {"openalex": 10, "scopus": 40, "arxiv": 1},
            "openalex_id": "W1",
            "scopus_id": "851",
            "arxiv_id": "2401.00001",
            "arxiv_version": "3",
            "grants": [
                {
                    "grant_number": "R01X",
                    "funder": "NIH",
                    "agency": "NIH",
                    "provider": "openalex",
                },
                {
                    "grant_number": "R01X",
                    "funder": "NIH",
                    "agency": "NIH",
                    "provider": "scopus",
                },
            ],
        }
    )
    assert row["Citation Count"] == "10"
    assert "OpenAlex:10" in row["Citations by Provider"]
    assert "Scopus:40" in row["Citations by Provider"]
    assert row["OpenAlex ID"] == "W1"
    assert row["Scopus ID"] == "851"
    assert row["arXiv Version"] == "3"
    assert row["Sources"] == "OpenAlex | arXiv | Scopus"
    assert row["Grant Numbers"] == "R01X | R01X"
    assert row["Grant Providers"] == "OpenAlex | Scopus"


def test_sources_include_enrichment_providers_only_when_they_contributed():
    with_arxiv = publication_item_to_row_dict(
        {
            "title": "Preprint",
            "authors": [{"name": "Ada"}],
            "providers": ["openalex"],
            "openalex_id": "W2",
            "arxiv_id": "2302.10767",
            "url": "https://example.com",
            "journal": "Nature",
            "publication_date": "2023-01-01",
            "grants": [],
        }
    )
    assert with_arxiv["Sources"] == "OpenAlex | arXiv"

    bare_openalex = publication_item_to_row_dict(
        {
            "title": "OA only",
            "authors": [{"name": "Ada"}],
            "providers": ["openalex", "scopus"],
            "openalex_id": "W3",
            "url": "https://example.com",
            "journal": "Nature",
            "publication_date": "2023-01-01",
            "grants": [],
        }
    )
    # Scopus listed in providers but contributed no id/citations/grants.
    assert bare_openalex["Sources"] == "OpenAlex"


def test_grant_export_normalizes_formatting_noise_keeps_uncertain_separate():
    row = publication_item_to_row_dict(
        {
            "title": "Noisy Grants",
            "authors": [{"name": "Ada"}],
            "providers": ["openalex"],
            "openalex_id": "W4",
            "url": "https://example.com",
            "journal": "Nature",
            "publication_date": "2023-01-01",
            "grants": [
                {
                    "award_id": "DE-AC02-05CH11231.",
                    "funder_name": "DOE",
                    "provider": "openalex",
                },
                {
                    "award_id": "DE AC02 05CH11231",
                    "funder_name": "DOE",
                    "provider": "openalex",
                },
                {
                    "award_id": "DEAC02\u201305CH11231",
                    "funder_name": "DOE",
                    "provider": "openalex",
                },
                {
                    "award_id": "-AC02-05CH11231",
                    "funder_name": "DOE",
                    "provider": "openalex",
                },
                {
                    "award_id": "05CH11231",
                    "funder_name": "NERSC",
                    "provider": "openalex",
                },
                {
                    "award_id": "DE-AC02-",
                    "funder_name": "DOE",
                    "provider": "openalex",
                },
                {
                    "award_id": "DE-SC0022289",
                    "funder_name": "DOE",
                    "provider": "openalex",
                },
                {
                    "award_id": "DE-SC0022289",
                    "funder_name": "DOE",
                    "provider": "openalex",
                },
            ],
        }
    )
    numbers = row["Grant Numbers"].split(" | ")
    assert numbers.count("DE-AC02-05CH11231") == 1
    assert "DE-AC02-05CH11231." not in numbers
    assert "DE AC02 05CH11231" not in numbers
    # Uncertain / partial IDs stay separate — not merged into the full DOE award.
    assert "05CH11231" in numbers
    assert "DE-AC02" in numbers
    assert "AC02-05CH11231" in numbers
    assert "DE-SC0022289" in numbers
    assert numbers.count("DE-SC0022289") == 1
    assert row["Grant Providers"] == "OpenAlex"
    assert "OpenAlex | OpenAlex" not in row["Grant Providers"]


@pytest.mark.asyncio
async def test_openalex_and_orcid_selection_export_same_corpus(session_factory):
    async with session_factory() as session:
        author = await _seed_author(session, name="Alp Sipahigil", openalex_id="AALP2")
        from app.db.models import ProviderAuthorRecord

        session.add(
            ProviderAuthorRecord(
                id=uuid.uuid4(),
                canonical_author_id=author.id,
                provider="orcid",
                provider_author_id="0000-0002-1111-2222",
                display_name="Alp Sipahigil",
                normalized_name="alp sipahigil",
                orcid="0000-0002-1111-2222",
            )
        )
        await _seed_work(
            session,
            title="Parity Paper",
            year=2020,
            provider_work_id="WPARITY",
            selected_authors=[author],
        )
        await _mark_verified(session, author.id, work_count=1)
        author_id = author.id

    oa_authors = [
        {
            "canonical_author_id": str(author_id),
            "display_name": "Alp Sipahigil",
            "provider": "openalex",
            "provider_author_id": "AALP2",
        }
    ]
    orcid_authors = [
        {
            "canonical_author_id": str(author_id),
            "display_name": "Alp Sipahigil",
            "provider": "orcid",
            "provider_author_id": "0000-0002-1111-2222",
        }
    ]
    with patch(
        "app.services.analysis.author_publications.search_works_by_author_ids",
        new_callable=AsyncMock,
    ):
        oa_export = client.post(
            "/api/analysis/authors/publications/export",
            json={"authors": oa_authors},
        )
        orcid_export = client.post(
            "/api/analysis/authors/publications/export",
            json={"authors": orcid_authors},
        )
    oa_header, oa_rows = _parse_csv(oa_export)
    orcid_header, orcid_rows = _parse_csv(orcid_export)
    assert [row[oa_header.index("Title")] for row in oa_rows] == [
        row[orcid_header.index("Title")] for row in orcid_rows
    ]
    assert oa_export.headers.get("x-corpus-source") == "stored_complete_corpus"
    assert orcid_export.headers.get("x-corpus-source") == "stored_complete_corpus"
