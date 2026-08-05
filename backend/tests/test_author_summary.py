"""Tests for author summary endpoint and enrichment."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, patch

import pytest
import pytest_asyncio
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.config import get_settings
from app.db.base import Base
from app.db.models import AuthorProfile, CanonicalAuthor, CanonicalAuthorInstitution, ProviderAuthorRecord
from app.integrations.arxiv.client import reset_arxiv_client_state_for_tests
from app.main import app
from app.services.authors.summary import get_author_summary
from app.services.analysis.work_authors import enrich_publication_items_authors, normalize_work_author

client = TestClient(app)


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
    get_settings.cache_clear()
    yield
    reset_arxiv_client_state_for_tests()
    get_settings.cache_clear()


@pytest.mark.asyncio
async def test_get_author_summary_returns_stored_profile_without_provider_call(session):
    canonical = CanonicalAuthor(
        id=uuid.uuid4(),
        preferred_name="Jane Doe",
        normalized_name="jane doe",
        resolution_status="merged",
    )
    session.add(canonical)
    await session.flush()

    profile = AuthorProfile(
        canonical_author_id=canonical.id,
        orcid="0000-0002-1825-0097",
        works_count=84,
        citation_count=1520,
        h_index=19,
        topics=["Genomics"],
        providers=["openalex"],
        enriched_at=datetime.now(UTC),
    )
    session.add(profile)
    session.add(
        CanonicalAuthorInstitution(
            id=uuid.uuid4(),
            canonical_author_id=canonical.id,
            institution_id="I1",
            institution_key="I1",
            institution_name="University of California, Berkeley",
            department="Department of Biology",
            country_code="US",
            is_current=True,
            provider="openalex",
        )
    )
    await session.commit()

    with patch(
        "app.services.authors.summary.fetch_openalex_author_payload",
        new_callable=AsyncMock,
    ) as mock_fetch:
        result = await get_author_summary(session, str(canonical.id))

    assert result["display_name"] == "Jane Doe"
    assert result["works_count"] == 84
    assert result["institutions"][0]["name"] == "University of California, Berkeley"
    mock_fetch.assert_not_awaited()


@pytest.mark.asyncio
async def test_get_author_summary_enriches_when_profile_stale(session):
    canonical = CanonicalAuthor(
        id=uuid.uuid4(),
        preferred_name="Jane Doe",
        normalized_name="jane doe",
        resolution_status="merged",
    )
    record = ProviderAuthorRecord(
        id=uuid.uuid4(),
        canonical_author_id=canonical.id,
        provider="openalex",
        provider_author_id="A1234567890",
        display_name="Jane Doe",
        normalized_name="jane doe",
    )
    session.add(canonical)
    session.add(record)
    session.add(
        AuthorProfile(
            canonical_author_id=canonical.id,
            works_count=10,
            providers=["openalex"],
            enriched_at=datetime.now(UTC) - timedelta(days=30),
        )
    )
    await session.commit()

    raw_payload = {
        "id": "https://openalex.org/A1234567890",
        "display_name": "Jane Doe",
        "orcid": "https://orcid.org/0000-0002-1825-0097",
        "works_count": 84,
        "cited_by_count": 1520,
        "summary_stats": {"h_index": 19},
        "topics": [{"id": "T1", "display_name": "Genomics"}],
        "affiliations": [
            {
                "institution": {
                    "id": "https://openalex.org/I1",
                    "display_name": "University of California, Berkeley",
                    "country_code": "US",
                },
                "years": [2022, 2023, 2024],
                "is_current": True,
            }
        ],
    }

    with patch(
        "app.services.authors.summary.fetch_openalex_author_payload",
        new_callable=AsyncMock,
        return_value=raw_payload,
    ):
        result = await get_author_summary(session, str(canonical.id))

    assert result["works_count"] == 84
    assert result["citation_count"] == 1520
    assert result["h_index"] == 19
    assert result["institutions"][0]["current"] is True


@pytest.mark.asyncio
async def test_enrich_publication_items_authors_adds_canonical_ids(session):
    canonical_id = uuid.uuid4()
    canonical = CanonicalAuthor(
        id=canonical_id,
        preferred_name="Jane Doe",
        normalized_name="jane doe",
        resolution_status="merged",
    )
    session.add(canonical)
    session.add(
        ProviderAuthorRecord(
            id=uuid.uuid4(),
            canonical_author_id=canonical_id,
            provider="openalex",
            provider_author_id="A1234567890",
            display_name="Jane Doe",
            normalized_name="jane doe",
        )
    )
    await session.commit()

    items = [
        {
            "id": "work-1",
            "title": "Paper",
            "authors": [{"id": "A1234567890", "name": "Jane Doe"}],
        }
    ]
    enriched = await enrich_publication_items_authors(session, items)
    author = enriched[0]["authors"][0]
    assert author["canonical_author_id"] == str(canonical_id)
    assert author["provider_ids"]["openalex"] == ["A1234567890"]


def test_normalize_work_author_marks_name_only_as_unresolved():
    author = normalize_work_author({"name": "Unknown Person"})
    assert author["unresolved"] is True
    assert author["canonical_author_id"] is None


@pytest.mark.asyncio
async def test_provider_error_falls_back_to_cached_profile(session):
    canonical = CanonicalAuthor(
        id=uuid.uuid4(),
        preferred_name="Jane Doe",
        normalized_name="jane doe",
        resolution_status="merged",
    )
    record = ProviderAuthorRecord(
        id=uuid.uuid4(),
        canonical_author_id=canonical.id,
        provider="openalex",
        provider_author_id="A1234567890",
        display_name="Jane Doe",
        normalized_name="jane doe",
    )
    session.add(canonical)
    session.add(record)
    session.add(
        AuthorProfile(
            canonical_author_id=canonical.id,
            works_count=50,
            citation_count=900,
            providers=["openalex"],
            enriched_at=datetime.now(UTC) - timedelta(days=30),
        )
    )
    await session.commit()

    from app.integrations.openalex.client import OpenAlexApiError

    with patch(
        "app.services.authors.summary.fetch_openalex_author_payload",
        new_callable=AsyncMock,
        side_effect=OpenAlexApiError("Provider unavailable"),
    ):
        result = await get_author_summary(session, str(canonical.id))

    assert result["works_count"] == 50
    assert result["citation_count"] == 900
