"""Regression: stored-corpus Analyze table must keep OpenAlex grants after enrichment."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from unittest.mock import AsyncMock

import httpx
import pytest
import pytest_asyncio
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from app.core.config import get_settings
from app.db.base import Base
from app.db.models import (
    AuthorWorkSyncState,
    CanonicalWork,
    ProviderWorkRecord,
    WorkAuthorship,
    WorkGrantMatch,
)
from app.integrations.elsevier.client import ElsevierClient
from app.services.analysis.author_publications import analyze_author_publications
from app.services.analysis.publication_enrichment import PublicationEnrichmentService
from app.services.work_persistence.candidate import candidate_from_provider_result
from app.services.work_persistence.service import WorkPersistenceService
from tests.test_author_insights import _author_payload, _seed_author


@pytest_asyncio.fixture
async def session():
    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    async with factory() as db:
        yield db
    await engine.dispose()


def _meta_payload(scopus_id: str = "85111111111") -> dict:
    return {
        "abstracts-retrieval-response": {
            "coredata": {
                "eid": f"2-s2.0-{scopus_id}",
                "dc:identifier": f"SCOPUS_ID:{scopus_id}",
                "citedby-count": "7",
                "dc:title": "Grant-backed paper",
                "prism:publicationName": "Nature",
                "prism:coverDate": "2024-01-01",
                "prism:doi": "10.1038/grants-example",
            }
        }
    }


async def _mark_verified_complete(
    session: AsyncSession,
    *,
    author_id: uuid.UUID,
    work_count: int = 1,
) -> None:
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


@pytest.mark.asyncio
async def test_stored_corpus_keeps_grants_after_enrichment(session, monkeypatch):
    """OpenAlex grants must survive enrichment and appear on stored-corpus pages."""
    monkeypatch.setenv("ELSEVIER_API_KEY", "test-key")
    monkeypatch.setenv("ARXIV_ENABLED", "false")
    monkeypatch.setenv("PUBLICATION_ENRICHMENT_ENABLED", "true")
    monkeypatch.setenv("AUTHOR_WORK_SYNC_TTL_SECONDS", str(18 * 60 * 60))
    get_settings.cache_clear()

    author = await _seed_author(session, name="Grant Author", openalex_id="A111")
    persistence = WorkPersistenceService(session)
    openalex_row = {
        "result_id": "openalex:W-GRANT",
        "result_type": "work",
        "source": "openalex",
        "openalex_id": "W-GRANT",
        "title": "Grant-backed paper",
        "publication_year": 2024,
        "doi": "10.1038/grants-example",
        "arxiv_id": "2401.99999",
        "citation_count": 3,
        "cited_by_count": 3,
        "journal": "Nature",
        "authors": [
            {
                "id": "A111",
                "name": "Grant Author",
                "provider_ids": {"openalex": ["A111"], "orcid": [], "arxiv": []},
            }
        ],
        "grants": [
            {
                "award_id": "R01GM123456",
                "funder_name": "National Institutes of Health",
                "verified": True,
                "match_type": "structured_award_relationship",
                "provider": "openalex",
            }
        ],
    }
    candidate = candidate_from_provider_result(openalex_row, provider="openalex")
    assert candidate is not None
    work, created = await persistence.resolve_candidate(candidate)
    assert created is True
    await _mark_verified_complete(session, author_id=author.id)

    grant_rows = (
        await session.execute(
            select(WorkGrantMatch).where(WorkGrantMatch.canonical_work_id == work.id)
        )
    ).scalars().all()
    assert len(grant_rows) == 1
    assert grant_rows[0].grant_number == "R01GM123456"
    assert grant_rows[0].provider == "openalex"
    before_grant_count = (
        await session.execute(select(func.count()).select_from(WorkGrantMatch))
    ).scalar_one()
    before_work_count = (
        await session.execute(select(func.count()).select_from(CanonicalWork))
    ).scalar_one()

    client = ElsevierClient()
    client.get_abstract_doi = AsyncMock(
        return_value=httpx.Response(
            200,
            json=_meta_payload(),
            request=httpx.Request("GET", "https://api.elsevier.com/"),
        )
    )
    metrics = await PublicationEnrichmentService(
        session, elsevier_client=client
    ).enrich_canonical_works([work.id])
    assert metrics.enriched["scopus"] == 1
    assert metrics.created_canonical_works == 0

    after_grant_count = (
        await session.execute(select(func.count()).select_from(WorkGrantMatch))
    ).scalar_one()
    after_work_count = (
        await session.execute(select(func.count()).select_from(CanonicalWork))
    ).scalar_one()
    assert after_grant_count == before_grant_count
    assert after_work_count == before_work_count
    oa_grants = (
        await session.execute(
            select(WorkGrantMatch).where(
                WorkGrantMatch.canonical_work_id == work.id,
                WorkGrantMatch.provider == "openalex",
            )
        )
    ).scalars().all()
    assert len(oa_grants) == 1

    result = await analyze_author_publications(
        session,
        authors=[
            {
                **_author_payload(author.id, "Grant Author"),
                "provider": "openalex",
                "provider_author_id": "A111",
            }
        ],
        limit=20,
        page=1,
    )
    assert result["corpus_source"] == "stored_complete_corpus"
    assert len(result["items"]) == 1
    item = result["items"][0]
    assert item["grants"], "stored-corpus page must include OpenAlex grants"
    assert item["grants"][0]["award_id"] == "R01GM123456"
    assert item["grants"][0]["provider"] == "openalex"
    assert item["grants"][0]["funder_name"] == "National Institutes of Health"
    providers = set(item.get("providers") or [])
    assert "openalex" in providers
    assert "scopus" in providers
    get_settings.cache_clear()


@pytest.mark.asyncio
async def test_raw_metadata_grants_hydrate_when_work_grant_matches_missing(session, monkeypatch):
    """Legacy synced works: grants only in OpenAlex raw_metadata must still display."""
    monkeypatch.setenv("ARXIV_ENABLED", "false")
    monkeypatch.setenv("AUTHOR_WORK_SYNC_TTL_SECONDS", str(18 * 60 * 60))
    get_settings.cache_clear()

    author = await _seed_author(session, name="Legacy Author", openalex_id="A222")
    work = CanonicalWork(
        id=uuid.uuid4(),
        title="Legacy grant paper",
        normalized_title="legacy grant paper",
        publication_year=2023,
        doi="10.1000/legacy",
    )
    session.add(work)
    await session.flush()
    session.add(
        ProviderWorkRecord(
            id=uuid.uuid4(),
            canonical_work_id=work.id,
            provider="openalex",
            provider_work_id="W-LEGACY",
            raw_metadata={
                "title": "Legacy grant paper",
                "openalex_id": "W-LEGACY",
                "citation_count": 1,
                "grants": [
                    {
                        "award_id": "U01HG000001",
                        "funder_name": "NHGRI",
                        "verified": True,
                        "match_type": "structured_award_relationship",
                        "provider": "openalex",
                    }
                ],
            },
            retrieved_at=datetime.now(timezone.utc),
        )
    )
    session.add(
        WorkAuthorship(
            id=uuid.uuid4(),
            canonical_work_id=work.id,
            provider="openalex",
            provider_author_id="A222",
            canonical_author_id=author.id,
            display_name="Legacy Author",
            author_position=0,
            raw_metadata={"name": "Legacy Author"},
        )
    )
    await _mark_verified_complete(session, author_id=author.id)

    assert (
        await session.execute(select(func.count()).select_from(WorkGrantMatch))
    ).scalar_one() == 0

    result = await analyze_author_publications(
        session,
        authors=[
            {
                **_author_payload(author.id, "Legacy Author"),
                "provider": "openalex",
                "provider_author_id": "A222",
            }
        ],
        limit=20,
        page=1,
    )
    assert result["corpus_source"] == "stored_complete_corpus"
    assert result["items"][0]["grants"][0]["award_id"] == "U01HG000001"
    assert result["items"][0]["grants"][0]["provider"] == "openalex"
    get_settings.cache_clear()
