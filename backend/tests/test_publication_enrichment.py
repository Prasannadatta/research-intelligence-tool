"""Publication enrichment: enrich-only overlays, matching, cache, source-aware citations."""

from __future__ import annotations

from unittest.mock import AsyncMock

import httpx
import pytest
import pytest_asyncio
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from app.db.base import Base
from app.db.models import CanonicalWork, ProviderWorkRecord
from app.integrations.elsevier.cited_by import (
    parse_scopus_abstract_enrichment,
    scopus_enrichment_as_provider_result,
)
from app.integrations.elsevier.client import ElsevierClient
from app.services.analysis.publication_enrichment import (
    PublicationEnrichmentService,
    preferred_citation_count,
)
from app.services.work_persistence.candidate import candidate_from_provider_result
from app.services.work_persistence.normalization import arxiv_id_from_doi
from app.services.work_persistence.service import WorkPersistenceService


@pytest_asyncio.fixture
async def session():
    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        poolclass=StaticPool,
        connect_args={"check_same_thread": False},
    )
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    async with factory() as db:
        yield db
    await engine.dispose()


def _response(status: int, payload: dict) -> httpx.Response:
    return httpx.Response(
        status,
        json=payload,
        request=httpx.Request("GET", "https://api.elsevier.com/"),
    )


def _meta_payload(
    *,
    scopus_id: str = "85111111111",
    citedby_count: str = "42",
    journal: str = "Nature Physics",
    title: str = "A Quantum Paper",
) -> dict:
    return {
        "abstracts-retrieval-response": {
            "coredata": {
                "eid": f"2-s2.0-{scopus_id}",
                "dc:identifier": f"SCOPUS_ID:{scopus_id}",
                "citedby-count": citedby_count,
                "dc:title": title,
                "prism:publicationName": journal,
                "prism:coverDate": "2024-03-15",
                "prism:doi": "10.1038/example",
                "prism:aggregationType": "Journal",
                "prism:issn": "1745-2473",
            }
        }
    }


async def _seed_openalex_work(
    session: AsyncSession,
    *,
    title: str = "A Quantum Paper",
    doi: str | None = "10.1038/example",
    arxiv_id: str | None = "2401.12345",
    openalex_citations: int = 10,
) -> CanonicalWork:
    service = WorkPersistenceService(session)
    row = {
        "result_id": "openalex:W1",
        "result_type": "work",
        "source": "openalex",
        "openalex_id": "W1",
        "title": title,
        "publication_year": 2024,
        "doi": doi,
        "arxiv_id": arxiv_id,
        "citation_count": openalex_citations,
        "cited_by_count": openalex_citations,
        "journal": "OpenAlex Venue",
        "authors": [{"name": "Ada Lovelace"}],
    }
    candidate = candidate_from_provider_result(row, provider="openalex")
    assert candidate is not None
    work, created = await service.resolve_candidate(candidate)
    assert created is True
    await session.commit()
    return work


def test_preferred_citation_count_prefers_openalex_never_sums():
    assert preferred_citation_count({"openalex": 10, "scopus": 42}) == 10
    assert preferred_citation_count({"scopus": 42, "arxiv": None}) == 42
    # Conflicting values must not be added or max-merged into a single inflated total.
    assert preferred_citation_count({"openalex": 10, "scopus": 999}) == 10
    assert preferred_citation_count({}) is None


def test_arxiv_id_from_doi():
    assert arxiv_id_from_doi("10.48550/arXiv.2401.12345") == "2401.12345"
    assert arxiv_id_from_doi("https://doi.org/10.48550/arxiv.1234.56789") == "1234.56789"
    assert arxiv_id_from_doi("10.1038/example") is None


def test_parse_scopus_abstract_enrichment_fields():
    enrichment = parse_scopus_abstract_enrichment(_meta_payload())
    assert enrichment is not None
    assert enrichment.scopus_id == "85111111111"
    assert enrichment.citedby_count == 42
    assert enrichment.publication_name == "Nature Physics"
    assert enrichment.publication_year == 2024
    row = scopus_enrichment_as_provider_result(enrichment, fallback_title="Fallback")
    assert row["citation_count"] == 42
    assert row["journal"] == "Nature Physics"
    assert row["source"] == "scopus"


@pytest.mark.asyncio
async def test_enrich_scopus_by_doi_no_new_canonical(session, monkeypatch):
    monkeypatch.setenv("ELSEVIER_API_KEY", "test-key")
    monkeypatch.setenv("PUBLICATION_ENRICHMENT_ENABLED", "true")
    from app.core.config import get_settings

    get_settings.cache_clear()

    work = await _seed_openalex_work(session)
    before = (
        await session.execute(select(func.count()).select_from(CanonicalWork))
    ).scalar_one()

    client = ElsevierClient()
    client.get_abstract_doi = AsyncMock(return_value=_response(200, _meta_payload()))

    service = PublicationEnrichmentService(session, elsevier_client=client)
    metrics = await service.enrich_canonical_works([work.id])

    after = (
        await session.execute(select(func.count()).select_from(CanonicalWork))
    ).scalar_one()
    assert after == before
    assert metrics.created_canonical_works == 0
    assert metrics.enriched["scopus"] == 1
    assert metrics.provider_calls["scopus"] == 1

    records = (
        await session.execute(select(ProviderWorkRecord).where(ProviderWorkRecord.provider == "scopus"))
    ).scalars().all()
    assert len(records) == 1
    assert records[0].canonical_work_id == work.id
    assert records[0].raw_metadata["citation_count"] == 42

    # Cache hit: second run must not call Elsevier again.
    client.get_abstract_doi.reset_mock()
    metrics2 = await PublicationEnrichmentService(session, elsevier_client=client).enrich_canonical_works(
        [work.id]
    )
    assert client.get_abstract_doi.await_count == 0
    assert metrics2.cache_hits["scopus"] >= 1
    get_settings.cache_clear()


@pytest.mark.asyncio
async def test_enrich_arxiv_by_id_overlay(session, monkeypatch):
    monkeypatch.setenv("ARXIV_ENABLED", "true")
    monkeypatch.setenv("PUBLICATION_ENRICHMENT_ENABLED", "true")
    from app.core.config import get_settings

    get_settings.cache_clear()

    work = await _seed_openalex_work(session, doi=None, arxiv_id="2401.12345")
    before = (
        await session.execute(select(func.count()).select_from(CanonicalWork))
    ).scalar_one()

    async def fake_fetch(ids, **_kwargs):
        return [
            {
                "result_id": "arxiv:2401.12345",
                "result_type": "work",
                "source": "arxiv",
                "source_id": "2401.12345",
                "arxiv_id": "2401.12345",
                "arxiv_version": "2",
                "title": "A Quantum Paper",
                "work_type": "preprint",
                "publication_year": 2024,
                "publication_date": "2024-01-15",
                "updated_date": "2024-02-01",
                "primary_source": "arXiv",
                "journal": "arXiv",
                "authors": [{"name": "Ada Lovelace"}],
                "cited_by_count": None,
            }
        ]

    monkeypatch.setattr(
        "app.services.analysis.publication_enrichment.fetch_arxiv_works_by_ids",
        fake_fetch,
    )

    metrics = await PublicationEnrichmentService(session).enrich_canonical_works([work.id])
    after = (
        await session.execute(select(func.count()).select_from(CanonicalWork))
    ).scalar_one()
    assert after == before
    assert metrics.created_canonical_works == 0
    assert metrics.enriched["arxiv"] == 1
    assert metrics.provider_calls["arxiv"] == 1

    record = (
        await session.execute(
            select(ProviderWorkRecord).where(ProviderWorkRecord.provider == "arxiv")
        )
    ).scalar_one()
    assert record.canonical_work_id == work.id
    assert record.raw_metadata.get("arxiv_version") == "2"
    assert record.raw_metadata.get("work_type") == "preprint"
    get_settings.cache_clear()


@pytest.mark.asyncio
async def test_source_aware_citations_not_max_merged(session):
    from app.services.analysis.author_insights import AuthorInsightsService

    work = await _seed_openalex_work(session, openalex_citations=10)
    service = WorkPersistenceService(session)
    scopus_row = scopus_enrichment_as_provider_result(
        parse_scopus_abstract_enrichment(_meta_payload(citedby_count="999")),
        fallback_title=work.title,
    )
    candidate = candidate_from_provider_result(scopus_row, provider="scopus")
    assert candidate is not None
    attached = await service.attach_enrichment_to_existing(
        canonical_work_id=work.id,
        candidate=candidate,
    )
    assert attached is not None
    await session.commit()

    insights = await AuthorInsightsService(session)._load_stored_work_insights({str(work.id)})
    stored = insights[str(work.id)]
    assert stored.citations_by_provider["openalex"] == 10
    assert stored.citations_by_provider["scopus"] == 999
    # Display count prefers OpenAlex; must not become 999 or 1009.
    assert stored.citation_count == 10


@pytest.mark.asyncio
async def test_attach_enrichment_rejects_doi_mismatch(session):
    work = await _seed_openalex_work(session, doi="10.1038/example")
    service = WorkPersistenceService(session)
    bad = candidate_from_provider_result(
        {
            "result_id": "scopus:1",
            "result_type": "work",
            "source": "scopus",
            "source_id": "1",
            "scopus_id": "1",
            "title": work.title,
            "doi": "10.9999/other",
            "citation_count": 1,
            "authors": [],
        },
        provider="scopus",
    )
    assert bad is not None
    assert (
        await service.attach_enrichment_to_existing(
            canonical_work_id=work.id,
            candidate=bad,
        )
        is None
    )


@pytest.mark.asyncio
async def test_enrichment_metrics_include_timing(session, monkeypatch):
    monkeypatch.setenv("ELSEVIER_API_KEY", "test-key")
    from app.core.config import get_settings

    get_settings.cache_clear()
    work = await _seed_openalex_work(session)
    client = ElsevierClient()
    client.get_abstract_doi = AsyncMock(return_value=_response(200, _meta_payload()))
    metrics = await PublicationEnrichmentService(session, elsevier_client=client).enrich_canonical_works(
        [work.id]
    )
    payload = metrics.as_dict()
    assert "elapsed_ms" in payload
    assert payload["elapsed_ms"]["total"] >= 0
    assert payload["provider_calls"]["scopus"] == 1
    get_settings.cache_clear()
