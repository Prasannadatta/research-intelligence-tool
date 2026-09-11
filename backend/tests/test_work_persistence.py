"""Focused tests for works persistence, sessions, cache, and grant provenance."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.db.base import Base
from app.db.models import ProviderSearchCache, ProviderWorkRecord, WorkGrantMatch
from app.services.work_persistence.candidate import candidate_from_provider_result
from app.services.work_persistence.normalization import normalize_title
from app.services.work_persistence.service import (
    WorkPersistenceService,
    build_provider_cache_key,
    persist_works_search_page,
)


@pytest_asyncio.fixture
async def session():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    async with factory() as db:
        yield db
    await engine.dispose()


def _work_row(
    *,
    provider: str,
    provider_work_id: str,
    title: str,
    year: int = 2024,
    authors: list[dict] | None = None,
    doi: str | None = None,
    arxiv_id: str | None = None,
    pmid: str | None = None,
    grant_number: str | None = None,
    grant_match: dict | None = None,
) -> dict:
    row = {
        "result_id": f"{provider}:{provider_work_id}",
        "result_type": "work",
        "title": title,
        "publication_year": year,
        "authors": authors
        or [{"id": None, "name": "Ada Lovelace"}],
        "doi": doi,
        "pmid": pmid,
        "arxiv_id": arxiv_id,
        "source": provider,
    }
    if provider == "openalex":
        row["openalex_id"] = provider_work_id
    else:
        row["source_id"] = provider_work_id
        if arxiv_id is None:
            row["arxiv_id"] = provider_work_id
    if grant_number:
        row["matched_grant_number"] = grant_number
        row["grant_match"] = grant_match or {
            "verified": provider == "openalex",
            "type": (
                "structured_award_relationship"
                if provider == "openalex"
                else "metadata_text_match"
            ),
        }
    return row


@pytest.mark.asyncio
async def test_idempotent_provider_record_upserts(session):
    service = WorkPersistenceService(session)
    row = _work_row(provider="openalex", provider_work_id="W1", title="Graph Neural Nets")
    candidate = candidate_from_provider_result(row, provider="openalex")
    first, created_first = await service.resolve_candidate(candidate)
    second, created_second = await service.resolve_candidate(candidate)
    await session.commit()

    assert created_first is True
    assert created_second is False
    assert first.id == second.id

    result = await session.execute(select(ProviderWorkRecord))
    assert len(result.scalars().all()) == 1


@pytest.mark.asyncio
async def test_same_doi_from_multiple_providers_merges(session):
    service = WorkPersistenceService(session)
    openalex = candidate_from_provider_result(
        _work_row(
            provider="openalex",
            provider_work_id="W100",
            title="Shared DOI Paper",
            doi="10.1000/xyz",
            authors=[{"name": "Alice"}],
        ),
        provider="openalex",
    )
    arxiv = candidate_from_provider_result(
        _work_row(
            provider="arxiv",
            provider_work_id="2401.00001",
            title="Shared DOI Paper (arXiv)",
            doi="https://doi.org/10.1000/XYZ",
            authors=[{"name": "Alice"}],
        ),
        provider="arxiv",
    )
    left, _ = await service.resolve_candidate(openalex)
    right, _ = await service.resolve_candidate(arxiv)
    await session.commit()

    assert left.id == right.id
    result = await session.execute(select(ProviderWorkRecord))
    assert len(result.scalars().all()) == 2


@pytest.mark.asyncio
async def test_same_title_same_year_different_month_not_merged(session):
    service = WorkPersistenceService(session)
    left = candidate_from_provider_result(
        {
            **_work_row(
                provider="openalex",
                provider_work_id="W-jan",
                title="Shared Title Paper",
                year=2024,
                authors=[{"name": "Ada Lovelace"}],
            ),
            "publication_date": "2024-01-15",
        },
        provider="openalex",
    )
    right = candidate_from_provider_result(
        {
            **_work_row(
                provider="openalex",
                provider_work_id="W-jun",
                title="Shared Title Paper",
                year=2024,
                authors=[{"name": "Ada Lovelace"}],
            ),
            "publication_date": "2024-06-01",
        },
        provider="openalex",
    )
    a, _ = await service.resolve_candidate(left)
    b, _ = await service.resolve_candidate(right)
    await session.commit()
    assert a.id != b.id


@pytest.mark.asyncio
async def test_same_title_same_year_without_month_not_merged(session):
    """Year-only timing is not strong enough — prefer keeping possible duplicates."""
    service = WorkPersistenceService(session)
    left = candidate_from_provider_result(
        _work_row(
            provider="openalex",
            provider_work_id="W-a",
            title="Year Only Paper",
            year=2023,
            authors=[{"name": "Ada Lovelace"}],
        ),
        provider="openalex",
    )
    right = candidate_from_provider_result(
        _work_row(
            provider="openalex",
            provider_work_id="W-b",
            title="Year Only Paper",
            year=2023,
            authors=[{"name": "Ada Lovelace"}],
        ),
        provider="openalex",
    )
    a, _ = await service.resolve_candidate(left)
    b, _ = await service.resolve_candidate(right)
    await session.commit()
    assert a.id != b.id


@pytest.mark.asyncio
async def test_same_doi_across_versions_merged(session):
    service = WorkPersistenceService(session)
    journal = candidate_from_provider_result(
        {
            **_work_row(
                provider="openalex",
                provider_work_id="W-journal",
                title="Versioned Paper",
                year=2024,
                doi="10.1000/versioned",
                authors=[{"name": "Ada Lovelace"}],
            ),
            "publication_date": "2024-08-01",
        },
        provider="openalex",
    )
    preprint = candidate_from_provider_result(
        {
            **_work_row(
                provider="openalex",
                provider_work_id="W-preprint",
                title="Versioned Paper",
                year=2024,
                doi="10.1000/versioned",
                authors=[{"name": "Ada Lovelace"}],
            ),
            "publication_date": "2024-02-10",
        },
        provider="openalex",
    )
    a, _ = await service.resolve_candidate(journal)
    b, _ = await service.resolve_candidate(preprint)
    await session.commit()
    assert a.id == b.id


@pytest.mark.asyncio
async def test_same_arxiv_id_across_versions_merged(session):
    service = WorkPersistenceService(session)
    first = candidate_from_provider_result(
        _work_row(
            provider="arxiv",
            provider_work_id="2401.11111",
            title="ArXiv Twin A",
            year=2024,
            arxiv_id="2401.11111",
            authors=[{"name": "Ada Lovelace"}],
        ),
        provider="arxiv",
    )
    second = candidate_from_provider_result(
        _work_row(
            provider="openalex",
            provider_work_id="W-arxiv-twin",
            title="ArXiv Twin B",
            year=2024,
            arxiv_id="2401.11111",
            authors=[{"name": "Ada Lovelace"}],
        ),
        provider="openalex",
    )
    a, _ = await service.resolve_candidate(first)
    b, _ = await service.resolve_candidate(second)
    await session.commit()
    assert a.id == b.id


@pytest.mark.asyncio
async def test_same_title_author_year_month_merged(session):
    service = WorkPersistenceService(session)
    left = candidate_from_provider_result(
        {
            **_work_row(
                provider="openalex",
                provider_work_id="W-m1",
                title="Strong Timing Paper",
                year=2022,
                authors=[{"name": "Ada Lovelace"}],
            ),
            "publication_date": "2022-03-01",
        },
        provider="openalex",
    )
    right = candidate_from_provider_result(
        {
            **_work_row(
                provider="arxiv",
                provider_work_id="2203.99999",
                title="Strong Timing Paper",
                year=2022,
                authors=[{"name": "Ada Lovelace"}],
            ),
            "publication_date": "2022-03-18",
        },
        provider="arxiv",
    )
    a, _ = await service.resolve_candidate(left)
    b, _ = await service.resolve_candidate(right)
    await session.commit()
    assert a.id == b.id


@pytest.mark.asyncio
async def test_stable_canonical_work_ids(session):
    service = WorkPersistenceService(session)
    candidate = candidate_from_provider_result(
        _work_row(provider="openalex", provider_work_id="W9", title="Stable ID"),
        provider="openalex",
    )
    first, _ = await service.resolve_candidate(candidate)
    await session.commit()
    second, _ = await service.resolve_candidate(candidate)
    await session.commit()
    assert str(first.id) == str(second.id)


@pytest.mark.asyncio
async def test_session_excludes_duplicates_on_later_pages(session):
    page1 = {
        "query": "neural",
        "entity_type": "works",
        "source": "openalex",
        "results": [
            _work_row(provider="openalex", provider_work_id="W1", title="Paper One"),
            _work_row(provider="openalex", provider_work_id="W2", title="Paper Two"),
        ],
        "next_cursor": "page2",
        "has_more": True,
    }
    first = await persist_works_search_page(
        session,
        provider="openalex",
        entity="works",
        query="neural",
        filters={},
        cursor=None,
        limit=20,
        payload=page1,
        search_session_id=None,
        from_cache=True,
    )
    await session.commit()
    session_id = first["search_session_id"]
    assert len(first["results"]) == 2

    page2 = {
        "query": "neural",
        "entity_type": "works",
        "source": "openalex",
        "results": [
            _work_row(provider="openalex", provider_work_id="W1", title="Paper One"),
            _work_row(provider="openalex", provider_work_id="W3", title="Paper Three"),
        ],
        "next_cursor": None,
        "has_more": False,
    }
    second = await persist_works_search_page(
        session,
        provider="openalex",
        entity="works",
        query="neural",
        filters={},
        cursor="page2",
        limit=20,
        payload=page2,
        search_session_id=session_id,
        from_cache=True,
    )
    await session.commit()

    assert second["search_session_id"] == session_id
    assert len(second["results"]) == 1
    assert second["results"][0]["title"] == "Paper Three"
    ids = {row["result_id"] for row in first["results"] + second["results"]}
    assert len(ids) == 3


@pytest.mark.asyncio
async def test_repeated_search_session_pages_not_returning_duplicates(session):
    payload = {
        "query": "dup",
        "entity_type": "works",
        "source": "arxiv",
        "results": [
            _work_row(provider="arxiv", provider_work_id="2401.1", title="Only Once"),
        ],
        "next_cursor": "c2",
        "has_more": True,
    }
    first = await persist_works_search_page(
        session,
        provider="arxiv",
        entity="works",
        query="dup",
        filters={},
        cursor=None,
        limit=20,
        payload=payload,
        search_session_id=None,
        from_cache=True,
    )
    await session.commit()
    second = await persist_works_search_page(
        session,
        provider="arxiv",
        entity="works",
        query="dup",
        filters={},
        cursor="c2",
        limit=20,
        payload=payload,
        search_session_id=first["search_session_id"],
        from_cache=True,
    )
    await session.commit()
    assert len(first["results"]) == 1
    assert second["results"] == []


@pytest.mark.asyncio
async def test_provider_aware_cache_isolation(session):
    service = WorkPersistenceService(session)
    openalex_payload = {
        "query": "quantum",
        "entity_type": "works",
        "source": "openalex",
        "results": [_work_row(provider="openalex", provider_work_id="W1", title="OA")],
        "next_cursor": None,
        "has_more": False,
    }
    await service.store_provider_response(
        provider="openalex",
        entity="works",
        query="quantum",
        filters={},
        cursor=None,
        limit=20,
        response=openalex_payload,
    )
    await session.commit()

    hit = await service.get_cached_provider_response(
        provider="openalex",
        entity="works",
        query="quantum",
        filters={},
        cursor=None,
        limit=20,
    )
    miss = await service.get_cached_provider_response(
        provider="arxiv",
        entity="works",
        query="quantum",
        filters={},
        cursor=None,
        limit=20,
    )
    assert hit is not None
    assert hit["source"] == "openalex"
    assert miss is None

    openalex_key = build_provider_cache_key(
        provider="openalex",
        entity="works",
        normalized_query="quantum",
        filters={},
        cursor=None,
        limit=20,
    )
    arxiv_key = build_provider_cache_key(
        provider="arxiv",
        entity="works",
        normalized_query="quantum",
        filters={},
        cursor=None,
        limit=20,
    )
    assert openalex_key != arxiv_key
    assert openalex_key.startswith("openalex:")
    assert arxiv_key.startswith("arxiv:")


@pytest.mark.asyncio
async def test_expired_cache_entries_are_ignored(session):
    service = WorkPersistenceService(session)
    await service.store_provider_response(
        provider="openalex",
        entity="works",
        query="expired",
        filters={},
        cursor=None,
        limit=20,
        response={"results": [], "source": "openalex"},
    )
    await session.commit()

    key = build_provider_cache_key(
        provider="openalex",
        entity="works",
        normalized_query="expired",
        filters={},
        cursor=None,
        limit=20,
    )
    result = await session.execute(
        select(ProviderSearchCache).where(ProviderSearchCache.cache_key == key)
    )
    entry = result.scalar_one()
    entry.expires_at = datetime.now(timezone.utc) - timedelta(seconds=1)
    await session.commit()

    cached = await service.get_cached_provider_response(
        provider="openalex",
        entity="works",
        query="expired",
        filters={},
        cursor=None,
        limit=20,
    )
    assert cached is None


@pytest.mark.asyncio
async def test_openalex_verified_grant_provenance(session):
    payload = {
        "query": "NSF-123",
        "entity_type": "grants",
        "source": "openalex",
        "results": [
            _work_row(
                provider="openalex",
                provider_work_id="W55",
                title="Funded Paper",
                grant_number="NSF-123",
                grant_match={
                    "verified": True,
                    "type": "structured_award_relationship",
                },
            )
        ],
        "next_cursor": None,
        "has_more": False,
    }
    out = await persist_works_search_page(
        session,
        provider="openalex",
        entity="grants",
        query="NSF-123",
        filters={},
        cursor=None,
        limit=20,
        payload=payload,
        search_session_id=None,
        from_cache=True,
    )
    await session.commit()

    assert out["results"][0]["result_type"] == "work"
    result = await session.execute(select(WorkGrantMatch))
    match = result.scalar_one()
    assert match.verified is True
    assert match.match_type == "structured_award_relationship"
    assert match.provider == "openalex"


@pytest.mark.asyncio
async def test_arxiv_unverified_metadata_match_provenance(session):
    payload = {
        "query": "NIH-999",
        "entity_type": "grants",
        "source": "arxiv",
        "results": [
            _work_row(
                provider="arxiv",
                provider_work_id="2402.1",
                title="Mentions Grant",
                grant_number="NIH-999",
                grant_match={
                    "verified": False,
                    "type": "metadata_text_match",
                },
            )
        ],
        "next_cursor": None,
        "has_more": False,
    }
    out = await persist_works_search_page(
        session,
        provider="arxiv",
        entity="grants",
        query="NIH-999",
        filters={},
        cursor=None,
        limit=20,
        payload=payload,
        search_session_id=None,
        from_cache=True,
    )
    await session.commit()

    assert "matched_grant_number" in out["results"][0]
    result = await session.execute(select(WorkGrantMatch))
    match = result.scalar_one()
    assert match.verified is False
    assert match.match_type == "metadata_text_match"

    # Idempotent grant-work-provider uniqueness
    await persist_works_search_page(
        session,
        provider="arxiv",
        entity="grants",
        query="NIH-999",
        filters={},
        cursor=None,
        limit=20,
        payload=payload,
        search_session_id=None,
        from_cache=True,
    )
    await session.commit()
    result = await session.execute(select(WorkGrantMatch))
    assert len(result.scalars().all()) == 1
