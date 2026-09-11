"""Tests for author details endpoint (summary + stored grants/pubs)."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from unittest.mock import AsyncMock, patch

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.config import get_settings
from app.db.base import Base
from app.db.models import (
    AuthorProfile,
    CanonicalAuthor,
    CanonicalAuthorInstitution,
    CanonicalWork,
    ProviderAuthorRecord,
    ProviderWorkRecord,
    WorkAuthorship,
    WorkGrantMatch,
)
from app.integrations.arxiv.client import reset_arxiv_client_state_for_tests
from app.services.authors.affiliation_enrichment import reset_author_enrichment_caches_for_tests
from app.services.authors.details import get_author_details
from app.services.authors.summary import reset_author_summary_enrich_locks_for_tests


@pytest_asyncio.fixture
async def session():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    async with factory() as db:
        yield db
    await engine.dispose()


@pytest.fixture(autouse=True)
def _reset_settings(monkeypatch):
    monkeypatch.setenv("WORK_PERSISTENCE_ENABLED", "false")
    monkeypatch.setenv("AUTHOR_RESOLUTION_ENABLED", "true")
    monkeypatch.setenv("PROVIDER_SEARCH_CACHE_ENABLED", "false")
    monkeypatch.setenv("OPENALEX_API_KEY", "test-key")
    reset_arxiv_client_state_for_tests()
    reset_author_enrichment_caches_for_tests()
    reset_author_summary_enrich_locks_for_tests()
    get_settings.cache_clear()
    yield
    reset_arxiv_client_state_for_tests()
    reset_author_enrichment_caches_for_tests()
    reset_author_summary_enrich_locks_for_tests()
    get_settings.cache_clear()


@pytest.mark.asyncio
async def test_get_author_details_includes_provider_ids_grants_and_pubs(session):
    canonical = CanonicalAuthor(
        id=uuid.uuid4(),
        preferred_name="Jane Doe",
        normalized_name="jane doe",
        resolution_status="merged",
    )
    session.add(canonical)
    session.add(
        ProviderAuthorRecord(
            id=uuid.uuid4(),
            canonical_author_id=canonical.id,
            provider="openalex",
            provider_author_id="A1234567890",
            display_name="Jane Doe",
            normalized_name="jane doe",
            orcid="0000-0002-1825-0097",
        )
    )
    session.add(
        AuthorProfile(
            canonical_author_id=canonical.id,
            orcid="0000-0002-1825-0097",
            works_count=2,
            citation_count=30,
            h_index=2,
            topics=["Genomics"],
            providers=["openalex"],
            enriched_at=datetime.now(UTC),
            enrichment_meta={"openalex": datetime.now(UTC).isoformat()},
        )
    )
    session.add(
        CanonicalAuthorInstitution(
            id=uuid.uuid4(),
            canonical_author_id=canonical.id,
            institution_key="I1",
            institution_name="UC Berkeley",
            department="Biology",
            country_code="US",
            is_current=True,
            provider="openalex",
        )
    )

    work_hi = CanonicalWork(
        id=uuid.uuid4(),
        title="High Impact Paper",
        normalized_title="high impact paper",
        publication_year=2024,
        doi="10.1000/hi",
    )
    work_lo = CanonicalWork(
        id=uuid.uuid4(),
        title="Earlier Paper",
        normalized_title="earlier paper",
        publication_year=2020,
        doi="10.1000/lo",
    )
    session.add_all([work_hi, work_lo])
    await session.flush()

    for work, cites in ((work_hi, 100), (work_lo, 5)):
        session.add(
            WorkAuthorship(
                id=uuid.uuid4(),
                canonical_work_id=work.id,
                provider="openalex",
                provider_author_id="A1234567890",
                canonical_author_id=canonical.id,
                display_name="Jane Doe",
                author_position=0,
            )
        )
        session.add(
            ProviderWorkRecord(
                id=uuid.uuid4(),
                canonical_work_id=work.id,
                provider="openalex",
                provider_work_id=f"W{work.publication_year}",
                raw_metadata={
                    "cited_by_count": cites,
                    "primary_location": {"source": {"display_name": "Nature"}},
                },
            )
        )

    session.add(
        WorkGrantMatch(
            id=uuid.uuid4(),
            canonical_work_id=work_hi.id,
            provider="openalex",
            grant_number="ABC-123",
            normalized_grant_number="abc123",
            verified=True,
            match_type="exact",
            raw_metadata={"funder_display_name": "NSF"},
        )
    )
    await session.commit()

    with patch(
        "app.services.authors.summary.fetch_openalex_author_payload",
        new_callable=AsyncMock,
    ) as mock_fetch:
        result = await get_author_details(session, str(canonical.id))

    mock_fetch.assert_not_awaited()
    assert result["display_name"] == "Jane Doe"
    assert result["provider_ids"]["openalex"] == ["A1234567890"]
    assert result["provider_ids"]["orcid"] == ["0000-0002-1825-0097"]
    assert result["stored_publication_count"] == 2
    assert result["publications"][0]["title"] == "High Impact Paper"
    assert result["publications"][0]["citation_count"] == 100
    assert len(result["grants"]) == 1
    assert result["grants"][0]["award_id"] == "ABC-123"
    assert result["grants"][0]["provider"] == "openalex"


@pytest.mark.asyncio
async def test_get_author_details_graceful_without_stored_works(session):
    canonical = CanonicalAuthor(
        id=uuid.uuid4(),
        preferred_name="No Works",
        normalized_name="no works",
        resolution_status="merged",
    )
    session.add(canonical)
    session.add(
        AuthorProfile(
            canonical_author_id=canonical.id,
            works_count=0,
            providers=["openalex"],
            enriched_at=datetime.now(UTC),
            enrichment_meta={"openalex": datetime.now(UTC).isoformat()},
        )
    )
    await session.commit()

    result = await get_author_details(session, str(canonical.id))
    assert result["publications"] == []
    assert result["grants"] == []
    assert result["stored_publication_count"] == 0
