"""Focused tests for author identity resolution."""

from __future__ import annotations

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.db.base import Base
from app.services.author_resolution.candidate import AuthorCandidate, WorkRef, InstitutionRef
from app.services.author_resolution.normalization import normalize_author_name
from app.services.author_resolution.scoring import (
    DECISION_AUTO_MERGE,
    DECISION_POSSIBLE_DUPLICATE,
    DECISION_SEPARATE,
    score_candidate_pair,
)
from app.services.author_resolution.service import (
    AuthorResolutionService,
    resolve_author_page,
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


def test_normalize_handles_last_first_and_punctuation():
    assert normalize_author_name("Smith, John P.") == "john p smith"
    assert normalize_author_name("José García") == "jose garcia"


@pytest.mark.asyncio
async def test_exact_same_provider_record_is_idempotent(session):
    service = AuthorResolutionService(session, auto_merge_threshold=85)
    candidate = AuthorCandidate(
        provider="openalex",
        provider_author_id="A123",
        display_name="John P. Smith",
        works_count=10,
    )
    first, created_first = await service.resolve_candidate(candidate)
    second, created_second = await service.resolve_candidate(candidate)
    await session.commit()

    assert created_first is True
    assert created_second is False
    assert first["id"] == second["id"]
    assert len(first["source_records"]) == 1


@pytest.mark.asyncio
async def test_different_name_formats_with_shared_works_merge(session):
    service = AuthorResolutionService(session, auto_merge_threshold=85)
    left = AuthorCandidate(
        provider="openalex",
        provider_author_id="A1",
        display_name="John P. Smith",
        works=[WorkRef(id="openalex:W100", id_type="openalex")],
        works_count=5,
    )
    right = AuthorCandidate(
        provider="openalex",
        provider_author_id="A2",
        display_name="Smith, John P",
        works=[WorkRef(id="openalex:W100", id_type="openalex")],
        works_count=40,
    )
    first, _ = await service.resolve_candidate(left)
    second, _ = await service.resolve_candidate(right)
    await session.commit()

    assert first["id"] == second["id"]
    assert second["identity_resolution"]["status"] == "merged"
    providers = {(r["provider"], r["provider_author_id"]) for r in second["source_records"]}
    assert providers == {("openalex", "A1"), ("openalex", "A2")}


def test_same_name_and_institution_without_shared_works_is_uncertain():
    left = AuthorCandidate(
        provider="openalex",
        provider_author_id="A1",
        display_name="Jane Doe",
        institutions=[InstitutionRef(id="I1", name="UC Berkeley")],
    )
    right = AuthorCandidate(
        provider="openalex",
        provider_author_id="A2",
        display_name="Jane Doe",
        institutions=[InstitutionRef(id="I1", name="UC Berkeley")],
    )
    score = score_candidate_pair(
        left,
        right,
        auto_merge_threshold=85,
        possible_duplicate_threshold=60,
    )
    # Name+institution alone must never auto-merge.
    assert score.decision != DECISION_AUTO_MERGE
    assert score.decision in {
        DECISION_POSSIBLE_DUPLICATE,
        DECISION_SEPARATE,
    }


def test_conflicting_orcids_force_separate():
    left = AuthorCandidate(
        provider="openalex",
        provider_author_id="A1",
        display_name="Alex Kim",
        orcid="0000-0001-1111-1111",
        works=[WorkRef(id="W1")],
    )
    right = AuthorCandidate(
        provider="openalex",
        provider_author_id="A2",
        display_name="Alex Kim",
        orcid="0000-0002-2222-2222",
        works=[WorkRef(id="W1")],
    )
    score = score_candidate_pair(
        left,
        right,
        auto_merge_threshold=85,
        possible_duplicate_threshold=60,
    )
    assert score.decision == DECISION_SEPARATE


@pytest.mark.asyncio
async def test_duplicate_on_later_page_emits_replace_not_insert(session):
    page1 = await resolve_author_page(
        session,
        [
            {
                "result_type": "author",
                "source": "openalex",
                "openalex_id": "A1",
                "display_name": "John Smith",
                "alternative_names": [],
                "works_count": 3,
            }
        ],
        known_canonical_ids=set(),
    )
    known = set(page1["known_canonical_ids"])
    assert len(page1["items"]) == 1
    canonical_id = page1["items"][0]["author"]["id"]

    page2 = await resolve_author_page(
        session,
        [
            {
                "result_type": "author",
                "source": "openalex",
                "openalex_id": "A9",
                "display_name": "J. Smith",
                "alternative_names": [],
                "works_count": 12,
                # Force shared work via candidate mapping: inject through raw sample? 
                # Use AuthorCandidate path by resolving with works via openalex row alone
                # won't include works. Resolve via service instead.
            }
        ],
        known_canonical_ids=known,
    )
    # Without shared works, second author is a new insert.
    assert len(page2["items"]) == 1
    assert page2["items"][0]["author"]["id"] != canonical_id

    # Now a later page with a true duplicate of page1's provider record.
    page3 = await resolve_author_page(
        session,
        [
            {
                "result_type": "author",
                "source": "openalex",
                "openalex_id": "A1",
                "display_name": "John Smith",
                "alternative_names": ["J. Smith"],
                "works_count": 20,
            }
        ],
        known_canonical_ids=known,
    )
    assert page3["items"] == []
    assert len(page3["updates"]) == 1
    assert page3["updates"][0]["operation"] == "replace"
    assert page3["updates"][0]["canonical_author_id"] == canonical_id


@pytest.mark.asyncio
async def test_publication_count_difference_does_not_block_merge(session):
    service = AuthorResolutionService(session)
    left = AuthorCandidate(
        provider="openalex",
        provider_author_id="A10",
        display_name="Riley Chen",
        orcid="0000-0003-3333-3333",
        works_count=2,
    )
    right = AuthorCandidate(
        provider="openalex",
        provider_author_id="A11",
        display_name="Riley Chen",
        orcid="0000-0003-3333-3333",
        works_count=200,
    )
    first, _ = await service.resolve_candidate(left)
    second, _ = await service.resolve_candidate(right)
    await session.commit()
    assert first["id"] == second["id"]
    assert len(second["source_records"]) == 2


@pytest.mark.asyncio
async def test_provider_records_preserved_after_merge(session):
    service = AuthorResolutionService(session)
    a = AuthorCandidate(
        provider="openalex",
        provider_author_id="AX",
        display_name="Pat Lee",
        works=[WorkRef(id="arxiv:2401.1", id_type="arxiv")],
    )
    b = AuthorCandidate(
        provider="arxiv",
        provider_author_id="pat lee",
        display_name="Pat Lee",
        works=[WorkRef(id="arxiv:2401.1", id_type="arxiv")],
    )
    first, _ = await service.resolve_candidate(a)
    second, _ = await service.resolve_candidate(b)
    await session.commit()
    assert first["id"] == second["id"]
    assert {r["provider"] for r in second["source_records"]} == {"openalex", "arxiv"}


def test_auto_merge_requires_strong_evidence():
    left = AuthorCandidate(
        provider="openalex",
        provider_author_id="A1",
        display_name="Sam Ortiz",
    )
    right = AuthorCandidate(
        provider="openalex",
        provider_author_id="A2",
        display_name="Sam Ortiz",
    )
    score = score_candidate_pair(
        left,
        right,
        auto_merge_threshold=85,
        possible_duplicate_threshold=60,
    )
    assert score.decision != DECISION_AUTO_MERGE
