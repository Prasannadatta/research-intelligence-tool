"""Tests for author summary endpoint and enrichment."""

from __future__ import annotations

import asyncio
import uuid
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import pytest_asyncio
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.config import get_settings
from app.db.base import Base
from app.db.models import AuthorProfile, CanonicalAuthor, CanonicalAuthorInstitution, ProviderAuthorRecord
from app.integrations.arxiv.client import reset_arxiv_client_state_for_tests
from app.main import app
from app.services.authors.affiliation_enrichment import reset_author_enrichment_caches_for_tests
from app.services.authors.summary import (
    enrich_author_summary,
    get_author_summary,
    reset_author_summary_enrich_locks_for_tests,
)
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
    reset_author_enrichment_caches_for_tests()
    reset_author_summary_enrich_locks_for_tests()
    get_settings.cache_clear()
    yield
    reset_arxiv_client_state_for_tests()
    reset_author_enrichment_caches_for_tests()
    reset_author_summary_enrich_locks_for_tests()
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
        enrichment_meta={"openalex": datetime.now(UTC).isoformat()},
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
    assert result["provider_ids"]["orcid"] == ["0000-0002-1825-0097"]
    mock_fetch.assert_not_awaited()


@pytest.mark.asyncio
async def test_get_author_summary_does_not_block_on_stale_profile(session):
    """GET returns local snapshot immediately; stale OpenAlex is lazy via enrich."""
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
        orcid="0000-0002-1825-0097",
    )
    session.add(canonical)
    session.add(record)
    session.add(
        AuthorProfile(
            canonical_author_id=canonical.id,
            orcid="0000-0002-1825-0097",
            works_count=10,
            providers=["openalex"],
            enriched_at=datetime.now(UTC) - timedelta(days=30),
            enrichment_meta={"openalex": (datetime.now(UTC) - timedelta(days=30)).isoformat()},
        )
    )
    await session.commit()

    with patch(
        "app.services.authors.summary.fetch_openalex_author_payload",
        new_callable=AsyncMock,
    ) as mock_fetch, patch(
        "app.services.authors.summary.orcid_configured",
        return_value=True,
    ), patch(
        "app.services.authors.summary.elsevier_configured",
        return_value=True,
    ):
        result = await get_author_summary(session, str(canonical.id))

    assert result["works_count"] == 10
    assert "openalex" in result["enrichment"]["pending"]
    assert "orcid" in result["enrichment"]["pending"]
    assert "scopus" in result["enrichment"]["pending"]
    mock_fetch.assert_not_awaited()


@pytest.mark.asyncio
async def test_enrich_author_summary_refreshes_stale_openalex_and_affiliations(session):
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
        orcid="0000-0002-1825-0097",
    )
    session.add(canonical)
    session.add(record)
    session.add(
        AuthorProfile(
            canonical_author_id=canonical.id,
            orcid="0000-0002-1825-0097",
            works_count=10,
            providers=["openalex"],
            enriched_at=datetime.now(UTC) - timedelta(days=30),
            enrichment_meta={"openalex": (datetime.now(UTC) - timedelta(days=30)).isoformat()},
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
    ), patch(
        "app.services.authors.summary.orcid_configured",
        return_value=False,
    ), patch(
        "app.services.authors.summary.elsevier_configured",
        return_value=False,
    ), patch(
        "app.services.authors.affiliation_enrichment.orcid_configured",
        return_value=False,
    ), patch(
        "app.services.authors.affiliation_enrichment.elsevier_configured",
        return_value=False,
    ):
        result = await enrich_author_summary(session, str(canonical.id))

    assert result["works_count"] == 84
    assert result["citation_count"] == 1520
    assert result["h_index"] == 19
    assert result["institutions"][0]["current"] is True
    assert "openalex" in result["enrichment"]["contacted"]
    assert result["enrichment"]["pending"] == []


@pytest.mark.asyncio
async def test_enrich_orcid_scopus_source_aware_and_failure_safe(session):
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
            works_count=84,
            citation_count=1520,
            h_index=19,
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
            institution_id="I1",
            institution_name="University of California, Berkeley",
            department="OpenAlex Dept",
            country_code="US",
            is_current=True,
            provider="openalex",
        )
    )
    await session.commit()

    employments = {
        "affiliation-group": [
            {
                "summaries": [
                    {
                        "employment-summary": {
                            "organization": {
                                "name": "UC Berkeley",
                                "disambiguated-organization": {
                                    "disambiguated-organization-identifier": "grid.47840.3f",
                                },
                                "address": {"country": "US"},
                            },
                            "department-name": "EECS",
                            "end-date": None,
                        }
                    }
                ]
            }
        ]
    }

    scopus_payload = {
        "author-retrieval-response": [
            {
                "coredata": {"document-count": "90", "dc:identifier": "AUTHOR_ID:999"},
                "author-profile": {
                    "affiliation-current": {
                        "@id": "60000000",
                        "affiliation-name": "UC Berkeley",
                        "department": "Electrical Engineering",
                        "affiliation-country": "United States",
                    }
                },
            }
        ]
    }

    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = scopus_payload

    with patch(
        "app.services.authors.summary.orcid_configured",
        return_value=True,
    ), patch(
        "app.services.authors.summary.elsevier_configured",
        return_value=True,
    ), patch(
        "app.services.authors.affiliation_enrichment.orcid_configured",
        return_value=True,
    ), patch(
        "app.services.authors.affiliation_enrichment.elsevier_configured",
        return_value=True,
    ), patch(
        "app.services.authors.affiliation_enrichment.OrcidClient.get_employments",
        new_callable=AsyncMock,
        return_value=employments,
    ), patch(
        "app.services.authors.affiliation_enrichment.ElsevierClient.get_author_by_orcid",
        new_callable=AsyncMock,
        return_value=mock_response,
    ):
        result = await enrich_author_summary(session, str(canonical.id))

    providers = {row["sources"][0] for row in result["institutions"] if row.get("sources")}
    assert "orcid" in providers or any(
        (row.get("department") == "EECS") for row in result["institutions"]
    )
    # OpenAlex department must not be overwritten by Scopus when keys differ.
    openalex_row = next(
        row for row in result["institutions"] if row.get("sources") == ["openalex"]
    )
    assert openalex_row["department"] == "OpenAlex Dept"
    assert result["works_count"] == 84  # Scopus must not overwrite existing OA metrics
    assert result["enrichment"]["pending"] == []
    assert "999" in result["provider_ids"]["scopus"]
    assert "scopus" in result["providers"]

    # Second enrich should not re-hit providers (TTL cache + enrichment_meta).
    with patch(
        "app.services.authors.affiliation_enrichment.OrcidClient.get_employments",
        new_callable=AsyncMock,
    ) as mock_orcid, patch(
        "app.services.authors.affiliation_enrichment.ElsevierClient.get_author_by_orcid",
        new_callable=AsyncMock,
    ) as mock_scopus, patch(
        "app.services.authors.summary.orcid_configured",
        return_value=True,
    ), patch(
        "app.services.authors.summary.elsevier_configured",
        return_value=True,
    ), patch(
        "app.services.authors.affiliation_enrichment.orcid_configured",
        return_value=True,
    ), patch(
        "app.services.authors.affiliation_enrichment.elsevier_configured",
        return_value=True,
    ):
        again = await enrich_author_summary(session, str(canonical.id))

    assert again["enrichment"]["contacted"] == []
    mock_orcid.assert_not_awaited()
    mock_scopus.assert_not_awaited()


@pytest.mark.asyncio
async def test_enrich_provider_failure_keeps_local_summary(session):
    from app.integrations.orcid.client import OrcidApiError

    canonical = CanonicalAuthor(
        id=uuid.uuid4(),
        preferred_name="Jane Doe",
        normalized_name="jane doe",
        resolution_status="merged",
    )
    session.add(canonical)
    session.add(
        AuthorProfile(
            canonical_author_id=canonical.id,
            orcid="0000-0002-1825-0097",
            works_count=50,
            citation_count=900,
            providers=["openalex"],
            enriched_at=datetime.now(UTC),
            enrichment_meta={"openalex": datetime.now(UTC).isoformat()},
        )
    )
    await session.commit()

    with patch(
        "app.services.authors.summary.orcid_configured",
        return_value=True,
    ), patch(
        "app.services.authors.summary.elsevier_configured",
        return_value=False,
    ), patch(
        "app.services.authors.affiliation_enrichment.orcid_configured",
        return_value=True,
    ), patch(
        "app.services.authors.affiliation_enrichment.elsevier_configured",
        return_value=False,
    ), patch(
        "app.services.authors.affiliation_enrichment.OrcidClient.get_employments",
        new_callable=AsyncMock,
        side_effect=OrcidApiError("down"),
    ):
        result = await enrich_author_summary(session, str(canonical.id))

    assert result["works_count"] == 50
    assert result["citation_count"] == 900
    assert "orcid" not in result["enrichment"]["pending"]


@pytest.mark.asyncio
async def test_enrich_dedupes_in_flight_requests(session):
    canonical = CanonicalAuthor(
        id=uuid.uuid4(),
        preferred_name="Jane Doe",
        normalized_name="jane doe",
        resolution_status="merged",
    )
    session.add(canonical)
    session.add(
        AuthorProfile(
            canonical_author_id=canonical.id,
            orcid="0000-0002-1825-0097",
            works_count=10,
            providers=["openalex"],
            enriched_at=datetime.now(UTC),
            enrichment_meta={"openalex": datetime.now(UTC).isoformat()},
        )
    )
    await session.commit()

    call_count = 0

    async def slow_employments(_orcid):
        nonlocal call_count
        call_count += 1
        await asyncio.sleep(0.05)
        return {"affiliation-group": []}

    with patch(
        "app.services.authors.summary.orcid_configured",
        return_value=True,
    ), patch(
        "app.services.authors.summary.elsevier_configured",
        return_value=False,
    ), patch(
        "app.services.authors.affiliation_enrichment.orcid_configured",
        return_value=True,
    ), patch(
        "app.services.authors.affiliation_enrichment.elsevier_configured",
        return_value=False,
    ), patch(
        "app.services.authors.affiliation_enrichment.OrcidClient.get_employments",
        new_callable=AsyncMock,
        side_effect=slow_employments,
    ):
        first, second = await asyncio.gather(
            enrich_author_summary(session, str(canonical.id)),
            enrich_author_summary(session, str(canonical.id)),
        )

    assert first["works_count"] == 10
    assert second["works_count"] == 10
    assert call_count == 1


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
    """Cold GET that must sync OpenAlex falls back to empty/local on provider error."""
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
    # No usable profile — GET will attempt OpenAlex once.
    await session.commit()

    from app.integrations.openalex.client import OpenAlexApiError

    with patch(
        "app.services.authors.summary.fetch_openalex_author_payload",
        new_callable=AsyncMock,
        side_effect=OpenAlexApiError("Provider unavailable"),
    ):
        result = await get_author_summary(session, str(canonical.id))

    assert result["display_name"] == "Jane Doe"
    assert result["works_count"] is None


@pytest.mark.asyncio
async def test_openalex_only_summary_loads_aliases_without_missing_greenlet(session):
    from app.services.authors.summary import get_author_summary_by_openalex_id

    with patch(
        "app.services.authors.summary.fetch_openalex_author_payload",
        new_callable=AsyncMock,
        return_value={
            "id": "https://openalex.org/A999",
            "display_name": "Hover Author",
            "display_name_alternatives": ["H. Author", "Hover A."],
            "orcid": None,
            "works_count": 3,
            "cited_by_count": 10,
            "summary_stats": {"h_index": 2},
            "topics": [],
            "last_known_institutions": [],
        },
    ), patch(
        "app.services.authors.summary.normalize_openalex_author",
        return_value={
            "id": "A999",
            "display_name": "Hover Author",
            "alternative_names": ["H. Author", "Hover A."],
            "orcid": None,
            "works_count": 3,
            "cited_by_count": 10,
            "h_index": 2,
            "topics": [],
            "last_known_institutions": [],
        },
    ):
        result = await get_author_summary_by_openalex_id(session, "A999")

    assert result["display_name"] == "Hover Author"
    assert "H. Author" in result["aliases"]
    assert result["unresolved"] is True
