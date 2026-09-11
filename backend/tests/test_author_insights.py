"""Tests for the read-only author insights dashboard foundation."""

from __future__ import annotations

import logging
import uuid
from unittest.mock import AsyncMock, patch

import pytest
import pytest_asyncio
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from app.core.config import get_settings
from app.db.base import Base
from app.db.models import (
    AuthorWork,
    CanonicalAuthorInstitution,
    CanonicalAuthor,
    CanonicalWork,
    ProviderAuthorRecord,
    ProviderWorkRecord,
    WorkAuthorship,
    WorkGrantMatch,
)
from app.db.session import get_db_session
from app.main import app
from app.services.analysis.author_insights import (
    AuthorInsightsService,
    SelectedAuthor,
    build_author_combinations,
    build_insights_combinations,
    stable_author_combination_id,
)
from app.services.analysis.author_work_sync import STATUS_COMPLETE
from app.services.work_persistence.candidate import candidate_from_provider_result
from app.services.work_persistence.service import WorkPersistenceService

client = TestClient(app)


@pytest.fixture(autouse=True)
def _insights_http_uses_verified_local_corpus(monkeypatch):
    """Legacy Insights HTTP tests seed local works; skip live OpenAlex sync/enrichment."""

    async def _fake_sync(self, authors, **kwargs):
        return [
            {
                "canonical_author_id": str(row.get("canonical_author_id")),
                "provider": "openalex",
                "display_name": row.get("display_name") or "Selected author",
                "stored_work_count_before": 0,
                "existing_links_repaired": 0,
                "fetched_work_count": 0,
                "new_works": 0,
                "stored_work_count_after": 0,
                "provider_work_count": 0,
                "status": STATUS_COMPLETE,
                "network_skipped": True,
                "error_message": None,
                "rate_limited": False,
                "coverage_verified": True,
                "resume_cursor": None,
                "last_synced_at": None,
            }
            for row in authors
            if isinstance(row, dict) and row.get("canonical_author_id")
        ]

    async def _fake_enrich(session, authors):
        return {
            "provider_calls": {"arxiv": 0, "scopus": 0, "openalex": 0, "orcid": 0},
            "cache_hits": {"arxiv": 0, "scopus": 0},
            "enriched": {"arxiv": 0, "scopus": 0},
            "skipped": {"disabled": 1},
            "created_canonical_works": 0,
            "elapsed_ms": {"arxiv": 0.0, "scopus": 0.0, "total": 0.0},
            "works_considered": 0,
            "works_attempted": 0,
        }

    monkeypatch.setattr(
        "app.services.analysis.author_work_sync.AuthorWorkSyncService.synchronize_selected_authors",
        _fake_sync,
    )
    monkeypatch.setattr(
        "app.api.routes.analysis.enrich_selected_authors_publications",
        _fake_enrich,
    )
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


@pytest_asyncio.fixture
async def session_factory():
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
        await engine.dispose()


def _author_payload(author_id: uuid.UUID, name: str) -> dict:
    return {
        "canonical_author_id": str(author_id),
        "display_name": name,
    }


async def _seed_author(session: AsyncSession, *, name: str, openalex_id: str) -> CanonicalAuthor:
    author = CanonicalAuthor(
        id=uuid.uuid4(),
        preferred_name=name,
        normalized_name=name.lower(),
        resolution_status="merged",
    )
    session.add(author)
    await session.flush()
    session.add(
        ProviderAuthorRecord(
            id=uuid.uuid4(),
            canonical_author_id=author.id,
            provider="openalex",
            provider_author_id=openalex_id,
            display_name=name,
            normalized_name=name.lower(),
        )
    )
    return author


async def _seed_profile_institution(
    session: AsyncSession,
    *,
    author: CanonicalAuthor,
    institution_id: str | None,
    name: str,
    country: str | None = "US",
    is_current: bool = True,
    from_year: int | None = 2020,
) -> CanonicalAuthorInstitution:
    row = CanonicalAuthorInstitution(
        id=uuid.uuid4(),
        canonical_author_id=author.id,
        institution_id=institution_id,
        institution_key=institution_id or name.lower(),
        institution_name=name,
        country_code=country,
        is_current=is_current,
        valid_from_year=from_year,
        provider="openalex",
    )
    session.add(row)
    return row


async def _seed_work(
    session: AsyncSession,
    *,
    title: str,
    year: int,
    provider_work_id: str,
    selected_authors: list[CanonicalAuthor],
    citation_count: int | None = 0,
    venue: str = "Nature",
    institutions: list[str] | None = None,
    grant_number: str | None = None,
    extra_coauthors: list[str] | None = None,
    raw_institutions: list[dict] | None = None,
    author_institutions: list[dict | None] | None = None,
    issn: str | None = None,
) -> CanonicalWork:
    work = CanonicalWork(
        id=uuid.uuid4(),
        title=title,
        normalized_title=title.lower(),
        publication_year=year,
        normalized_first_author=selected_authors[0].preferred_name.lower(),
    )
    session.add(work)
    await session.flush()
    raw_metadata = {
        "title": title,
        "publication_year": year,
        "primary_source": venue,
    }
    if citation_count is not None:
        raw_metadata["cited_by_count"] = citation_count
    if issn:
        raw_metadata["issn"] = issn
    session.add(
        ProviderWorkRecord(
            id=uuid.uuid4(),
            canonical_work_id=work.id,
            provider="openalex",
            provider_work_id=provider_work_id,
            raw_metadata=raw_metadata,
        )
    )
    for index, author in enumerate(selected_authors):
        if author_institutions is not None and index < len(author_institutions):
            institution_payload = author_institutions[index]
            inst_rows = [institution_payload] if institution_payload else []
            inst = [
                str(institution_payload.get("id") or institution_payload.get("institution_id"))
            ] if institution_payload and (institution_payload.get("id") or institution_payload.get("institution_id")) else []
            countries = [
                str(institution_payload.get("country_code") or institution_payload.get("country"))
            ] if institution_payload and (institution_payload.get("country_code") or institution_payload.get("country")) else []
        else:
            inst = institutions[index : index + 1] if institutions else []
            inst_rows = [
                {"id": value, "display_name": value}
                for value in inst
            ]
            countries = []
        raw_metadata = {}
        if raw_institutions and index < len(raw_institutions):
            raw_metadata = {"institutions": [raw_institutions[index]]}
        session.add(
            WorkAuthorship(
                id=uuid.uuid4(),
                canonical_work_id=work.id,
                provider="openalex",
                provider_author_id=f"A{index + 1}",
                canonical_author_id=author.id,
                display_name=author.preferred_name,
                author_position=index,
                institutions=inst_rows,
                institution_ids=inst,
                countries=countries,
                raw_metadata=raw_metadata,
            )
        )
    for extra_index, name in enumerate(extra_coauthors or [], start=len(selected_authors)):
        session.add(
            WorkAuthorship(
                id=uuid.uuid4(),
                canonical_work_id=work.id,
                provider="openalex",
                provider_author_id=f"AX{extra_index}",
                canonical_author_id=None,
                display_name=name,
                author_position=extra_index,
                institutions=[],
                institution_ids=[],
                countries=[],
            )
        )
    if grant_number:
        session.add(
            WorkGrantMatch(
                id=uuid.uuid4(),
                canonical_work_id=work.id,
                provider="openalex",
                grant_number=grant_number,
                normalized_grant_number=grant_number.lower(),
                verified=True,
                match_type="structured_award_relationship",
                raw_metadata={"funder_name": "National Science Foundation"},
            )
        )
    return work


async def _seed_three_author_insights_fixture(session: AsyncSession):
    author_a = await _seed_author(session, name="Author A", openalex_id="A1")
    author_b = await _seed_author(session, name="Author B", openalex_id="A2")
    author_c = await _seed_author(session, name="Author C", openalex_id="A3")

    await _seed_work(
        session,
        title="AB One",
        year=2021,
        provider_work_id="WAB1",
        selected_authors=[author_a, author_b],
        citation_count=10,
        venue="Physical Review A",
        institutions=["I1", "I2"],
        grant_number="G-1",
    )
    await _seed_work(
        session,
        title="AB Two",
        year=2021,
        provider_work_id="WAB2",
        selected_authors=[author_a, author_b],
        citation_count=0,
        venue="physical review a",
    )
    await _seed_work(
        session,
        title="AC One",
        year=2022,
        provider_work_id="WAC1",
        selected_authors=[author_a, author_c],
        citation_count=20,
        venue="Nature",
    )
    await _seed_work(
        session,
        title="BC Missing Citation",
        year=2022,
        provider_work_id="WBC1",
        selected_authors=[author_b, author_c],
        citation_count=None,
        venue="Journal of Tests",
    )
    await _seed_work(
        session,
        title="ABC With Extra Coauthor",
        year=2023,
        provider_work_id="WABC1",
        selected_authors=[author_a, author_b, author_c],
        citation_count=30,
        venue="Physical Review A",
        grant_number="G-2",
        extra_coauthors=["Outside Collaborator"],
    )
    await _seed_work(
        session,
        title="A Solo",
        year=2021,
        provider_work_id="WA1",
        selected_authors=[author_a],
        citation_count=5,
        venue="Science",
    )
    await session.commit()
    return author_a, author_b, author_c


async def _seed_institution_insights_fixture(session: AsyncSession):
    author_a = await _seed_author(session, name="Author A", openalex_id="A1")
    author_b = await _seed_author(session, name="Author B", openalex_id="A2")
    author_c = await _seed_author(session, name="Author C", openalex_id="A3")
    author_d = await _seed_author(session, name="Author D", openalex_id="A4")

    await _seed_profile_institution(
        session,
        author=author_a,
        institution_id="I-PROFILE-A",
        name="Profile University",
        country="US",
    )
    await _seed_profile_institution(
        session,
        author=author_b,
        institution_id="I-PROFILE-B",
        name="Beta Profile University",
        country="US",
    )

    await _seed_work(
        session,
        title="AB Paper Affiliations",
        year=2022,
        provider_work_id="WI1",
        selected_authors=[author_a, author_b],
        citation_count=10,
        venue="Institution Journal",
        author_institutions=[
            {
                "id": "I-PAPER",
                "display_name": "Paper University",
                "country_code": "US",
            },
            {
                "id": "I-BETA",
                "display_name": "Beta University",
                "country_code": "UK",
            },
        ],
    )
    await _seed_work(
        session,
        title="AC Profile And Raw",
        year=2023,
        provider_work_id="WI2",
        selected_authors=[author_a, author_c],
        citation_count=20,
        venue="Institution Journal",
        raw_institutions=[
            {},
            {
                "id": "I-GAMMA",
                "display_name": "Gamma Institute",
                "country_code": "CA",
            },
        ],
        extra_coauthors=["Unknown Affiliation Coauthor"],
    )
    await _seed_work(
        session,
        title="ABC Three Institutions",
        year=2024,
        provider_work_id="WI3",
        selected_authors=[author_a, author_b, author_c],
        citation_count=30,
        venue="Institution Journal",
        author_institutions=[
            {
                "id": "I-PAPER",
                "display_name": "Paper Univ.",
                "country_code": "US",
            },
            {
                "id": "I-BETA",
                "display_name": "Beta University",
                "country_code": "UK",
            },
            {
                "id": "I-GAMMA",
                "display_name": "Gamma Institute",
                "country_code": "CA",
            },
        ],
    )
    await _seed_work(
        session,
        title="Duplicate Institution Variants",
        year=2024,
        provider_work_id="WI4",
        selected_authors=[author_a, author_b],
        citation_count=5,
        venue="Institution Journal",
        author_institutions=[
            {
                "display_name": "Example University, Inc.",
                "country_code": "US",
            },
            {
                "display_name": "example university inc",
                "country_code": "US",
            },
        ],
    )
    await _seed_work(
        session,
        title="Single Institution Work",
        year=2025,
        provider_work_id="WI5",
        selected_authors=[author_a, author_b],
        citation_count=1,
        venue="Institution Journal",
        author_institutions=[
            {
                "id": "I-PAPER",
                "display_name": "Paper University",
                "country_code": "US",
            },
            {
                "id": "I-PAPER",
                "display_name": "Paper University",
                "country_code": "US",
            },
        ],
    )
    await _seed_work(
        session,
        title="Unknown Institution Work",
        year=2025,
        provider_work_id="WI6",
        selected_authors=[author_d],
        citation_count=0,
        venue="Institution Journal",
    )
    await session.commit()
    return author_a, author_b, author_c, author_d


@pytest.mark.asyncio
async def test_endpoint_accepts_selected_canonical_authors(session_factory):
    async with session_factory() as session:
        author = await _seed_author(session, name="Ada Lovelace", openalex_id="A1")
        await _seed_work(
            session,
            title="Analytical Engines",
            year=2024,
            provider_work_id="W1",
            selected_authors=[author],
        )
        await session.commit()

    response = client.post(
        "/api/analysis/authors/insights",
        json={"authors": [_author_payload(author.id, "Ada Lovelace")]},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["authors"] == [
        {"canonical_author_id": str(author.id), "display_name": "Ada Lovelace"}
    ]
    assert payload["metrics"]["total_unique_publications"] == 1


@pytest.mark.asyncio
async def test_insights_does_not_call_providers_for_large_author_sets(session_factory):
    authors = []
    async with session_factory() as session:
        for index in range(7):
            authors.append(
                await _seed_author(
                    session,
                    name=f"Author {index}",
                    openalex_id=f"A{index}",
                )
            )
        await _seed_work(
            session,
            title="Shared Seven",
            year=2024,
            provider_work_id="W7",
            selected_authors=authors[:3],
        )
        await session.commit()

    with patch(
        "app.services.analysis.author_work_sync.search_works_by_author_ids",
        new_callable=AsyncMock,
    ) as mock_oa:
        response = client.post(
            "/api/analysis/authors/insights",
            json={
                "authors": [
                    _author_payload(author.id, author.preferred_name) for author in authors
                ]
            },
        )

    assert response.status_code == 200
    assert response.json()["combination_mode"] == "scalable"
    mock_oa.assert_not_awaited()


@pytest.mark.asyncio
async def test_insights_logs_phase_timings(session_factory, caplog):
    async with session_factory() as session:
        author = await _seed_author(session, name="Timing Author", openalex_id="A1")
        await _seed_work(
            session,
            title="Timing Paper",
            year=2024,
            provider_work_id="W1",
            selected_authors=[author],
        )
        await session.commit()

    with caplog.at_level(logging.INFO):
        response = client.post(
            "/api/analysis/authors/insights",
            json={"authors": [_author_payload(author.id, "Timing Author")]},
        )

    assert response.status_code == 200
    messages = " ".join(record.getMessage() for record in caplog.records)
    for phase in (
        "publication_work_loading",
        "collaboration_aggregation",
        "institution_aggregation",
        "journal_metrics",
        "total_request",
    ):
        assert f"phase={phase}" in messages
    assert "phase=author_sync" not in messages


@pytest.mark.asyncio
async def test_invalid_canonical_author_is_handled_cleanly(session_factory):
    missing = uuid.uuid4()
    response = client.post(
        "/api/analysis/authors/insights",
        json={"authors": [_author_payload(missing, "Missing Author")]},
    )

    assert response.status_code == 404
    assert "Canonical author not found" in response.json()["detail"]


@pytest.mark.asyncio
async def test_canonical_works_are_deduplicated(session_factory):
    async with session_factory() as session:
        author = await _seed_author(session, name="Grace Hopper", openalex_id="A1")
        work = await _seed_work(
            session,
            title="Compiler Notes",
            year=2023,
            provider_work_id="W1",
            selected_authors=[author],
        )
        session.add(
            ProviderWorkRecord(
                id=uuid.uuid4(),
                canonical_work_id=work.id,
                provider="arxiv",
                provider_work_id="2301.00001",
                raw_metadata={
                    "title": "Compiler Notes",
                    "publication_year": 2023,
                    "cited_by_count": 7,
                    "primary_source": "arXiv",
                },
            )
        )
        await session.commit()

    response = client.post(
        "/api/analysis/authors/insights",
        json={"authors": [_author_payload(author.id, "Grace Hopper")]},
    )

    assert response.status_code == 200
    assert response.json()["metrics"]["total_unique_publications"] == 1


@pytest.mark.asyncio
async def test_work_selected_author_membership_mapping_is_correct(session_factory):
    async with session_factory() as session:
        left = await _seed_author(session, name="Author A", openalex_id="A1")
        right = await _seed_author(session, name="Author B", openalex_id="A2")
        shared = await _seed_work(
            session,
            title="Shared Work",
            year=2022,
            provider_work_id="W1",
            selected_authors=[left, right],
        )
        solo = await _seed_work(
            session,
            title="Solo Work",
            year=2021,
            provider_work_id="W2",
            selected_authors=[left],
        )
        await session.commit()

        mapping = await AuthorInsightsService(session)._load_work_membership(
            [str(left.id), str(right.id)]
        )

    assert mapping[str(shared.id)] == {str(left.id), str(right.id)}
    assert mapping[str(solo.id)] == {str(left.id)}


def test_two_authors_produce_pair_combination_identity():
    authors = [
        SelectedAuthor("b", "Author B"),
        SelectedAuthor("a", "Author A"),
    ]

    combinations = build_author_combinations(authors)

    assert combinations == [
        (
            stable_author_combination_id(["a", "b"]),
            (
                SelectedAuthor("a", "Author A"),
                SelectedAuthor("b", "Author B"),
            ),
        )
    ]


def test_three_authors_produce_pair_and_triple_combination_identities():
    authors = [
        SelectedAuthor("a", "Author A"),
        SelectedAuthor("b", "Author B"),
        SelectedAuthor("c", "Author C"),
    ]

    combination_ids = [combo_id for combo_id, _authors in build_author_combinations(authors)]

    assert combination_ids == ["a+b", "a+c", "b+c", "a+b+c"]


def test_six_authors_keep_exhaustive_combination_mode():
    authors = [SelectedAuthor(f"a{index}", f"Author {index}") for index in range(6)]

    mode, combinations = build_insights_combinations(authors, {})

    assert mode == "all_combinations"
    assert len(combinations) == (2**6) - 6 - 1


def test_scalable_combinations_include_pairs_all_selected_and_observed_groups():
    authors = [SelectedAuthor(f"a{index}", f"Author {index}") for index in range(30)]
    triple = {authors[0].canonical_author_id, authors[1].canonical_author_id, authors[2].canonical_author_id}
    membership = {
        "pair-work": {authors[0].canonical_author_id, authors[1].canonical_author_id},
        "triple-work": triple,
    }

    mode, combinations = build_insights_combinations(authors, membership)
    combo_sizes = sorted(len(group) for _combo_id, group in combinations)

    assert mode == "scalable"
    assert len(combinations) == (30 * 29 // 2) + 1 + 1
    assert combo_sizes.count(2) == 30 * 29 // 2
    assert combo_sizes.count(3) == 1
    assert combo_sizes.count(30) == 1
    assert max(combo_sizes) == 30


def test_fifty_author_scalable_combinations_stay_polynomial():
    authors = [SelectedAuthor(f"a{index}", f"Author {index}") for index in range(50)]
    membership = {
        "observed": {
            authors[0].canonical_author_id,
            authors[1].canonical_author_id,
            authors[2].canonical_author_id,
            authors[3].canonical_author_id,
        }
    }

    mode, combinations = build_insights_combinations(authors, membership)

    assert mode == "scalable"
    assert len(combinations) == (50 * 49 // 2) + 1 + 1
    assert len(combinations) < 2000


async def _seed_scalable_author_set(session: AsyncSession, count: int) -> list[CanonicalAuthor]:
    authors = [
        await _seed_author(session, name=f"Scale Author {index}", openalex_id=f"S{index}")
        for index in range(count)
    ]
    for index in range(count - 1):
        await _seed_work(
            session,
            title=f"Pair {index}",
            year=2024,
            provider_work_id=f"WP{index}",
            selected_authors=[authors[index], authors[index + 1]],
        )
    await _seed_work(
        session,
        title="Observed Higher Order",
        year=2023,
        provider_work_id="WHIGH",
        selected_authors=authors[:4],
    )
    await session.commit()
    return authors


@pytest.mark.asyncio
async def test_thirty_author_insights_uses_scalable_combinations(session_factory):
    async with session_factory() as session:
        authors = await _seed_scalable_author_set(session, 30)

    with patch(
        "app.services.analysis.author_work_sync.search_works_by_author_ids",
        new_callable=AsyncMock,
    ) as mock_oa:
        response = client.post(
            "/api/analysis/authors/insights",
            json={
                "authors": [
                    _author_payload(author.id, author.preferred_name) for author in authors
                ]
            },
        )

    assert response.status_code == 200
    payload = response.json()
    assert payload["combination_mode"] == "scalable"
    assert len(payload["combinations"]) == (30 * 29 // 2) + 1 + 1
    mock_oa.assert_not_awaited()


@pytest.mark.asyncio
async def test_fifty_author_insights_uses_scalable_combinations(session_factory):
    async with session_factory() as session:
        authors = await _seed_scalable_author_set(session, 50)

    with patch(
        "app.services.analysis.author_work_sync.search_works_by_author_ids",
        new_callable=AsyncMock,
    ) as mock_oa:
        response = client.post(
            "/api/analysis/authors/insights",
            json={
                "authors": [
                    _author_payload(author.id, author.preferred_name) for author in authors
                ]
            },
        )

    assert response.status_code == 200
    payload = response.json()
    assert payload["combination_mode"] == "scalable"
    assert len(payload["combinations"]) == (50 * 49 // 2) + 1 + 1
    mock_oa.assert_not_awaited()


@pytest.mark.asyncio
async def test_three_author_dashboard_aggregations_are_real(session_factory):
    async with session_factory() as session:
        author_a, author_b, author_c = await _seed_three_author_insights_fixture(session)

    response = client.post(
        "/api/analysis/authors/insights",
        json={
            "authors": [
                _author_payload(author_a.id, "Author A"),
                _author_payload(author_b.id, "Author B"),
                _author_payload(author_c.id, "Author C"),
            ]
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["combination_mode"] == "all_combinations"

    assert payload["metrics"] == {
        "total_unique_publications": 6,
        "multi_selected_author_publications": 5,
        "all_selected_author_publications": 1,
        "multi_institution_publications": 1,
        "total_citations": 65,
        "average_citations": 13.0,
    }

    combinations = {row["label"]: row for row in payload["combinations"]}
    assert list(combinations.keys()) == [
        "Author A + Author B",
        "Author A + Author C",
        "Author B + Author C",
        "Author A + Author B + Author C",
    ]
    assert combinations["Author A + Author B"]["publication_count"] == 3
    assert combinations["Author A + Author B"]["citation_count"] == 40
    assert combinations["Author A + Author B"]["average_citations"] == 13.33
    assert combinations["Author A + Author B"]["grant_count"] == 2
    assert combinations["Author A + Author C"]["publication_count"] == 2
    assert combinations["Author B + Author C"]["publication_count"] == 2
    assert combinations["Author A + Author B + Author C"]["publication_count"] == 1
    assert payload["default_combination_id"] == combinations[
        "Author A + Author B + Author C"
    ]["id"]

    assert payload["participation"]["selected_author_counts"] == [
        {"selected_author_count": 1, "publication_count": 1},
        {"selected_author_count": 2, "publication_count": 4},
        {"selected_author_count": 3, "publication_count": 1},
    ]

    assert payload["collaboration_by_year"] == [
        {
            "year": 2021,
            "publication_count": 2,
            "percentage_of_year_total": 66.67,
        },
        {
            "year": 2022,
            "publication_count": 2,
            "percentage_of_year_total": 100.0,
        },
        {
            "year": 2023,
            "publication_count": 1,
            "percentage_of_year_total": 100.0,
        },
    ]

    assert payload["citation_activity"] == [
        {
            "year": 2021,
            "publication_count": 3,
            "citation_count": 15,
            "cumulative_citations": 15,
        },
        {
            "year": 2022,
            "publication_count": 2,
            "citation_count": 20,
            "cumulative_citations": 35,
        },
        {
            "year": 2023,
            "publication_count": 1,
            "citation_count": 30,
            "cumulative_citations": 65,
        },
    ]

    assert payload["top_journals"][0] == {
        "venue": "Physical Review A",
        "publication_count": 3,
        "citation_count": 40,
        "issn": None,
        "journal_metrics": None,
    }


@pytest.mark.asyncio
async def test_pairwise_combinations_use_union_not_all_author_intersection(session_factory):
    async with session_factory() as session:
        author_a, author_b, author_c = await _seed_three_author_insights_fixture(session)

    response = client.post(
        "/api/analysis/authors/insights",
        json={
            "authors": [
                _author_payload(author_a.id, "Author A"),
                _author_payload(author_b.id, "Author B"),
                _author_payload(author_c.id, "Author C"),
            ],
            "filters": {
                "from_year": None,
                "to_year": None,
                "sources": [],
                "venues": [],
                "grant_numbers": [],
            },
        },
    )

    assert response.status_code == 200
    payload = response.json()
    combinations = {row["label"]: row["publication_count"] for row in payload["combinations"]}

    assert payload["metrics"]["total_unique_publications"] == 6
    assert payload["metrics"]["all_selected_author_publications"] == 1
    assert combinations == {
        "Author A + Author B": 3,
        "Author A + Author C": 2,
        "Author B + Author C": 2,
        "Author A + Author B + Author C": 1,
    }
    assert combinations["Author A + Author B"] > combinations[
        "Author A + Author B + Author C"
    ]


@pytest.mark.asyncio
async def test_insight_filters_affect_every_aggregate_consistently(session_factory):
    async with session_factory() as session:
        author_a, author_b, author_c = await _seed_three_author_insights_fixture(session)

    response = client.post(
        "/api/analysis/authors/insights",
        json={
            "authors": [
                _author_payload(author_a.id, "Author A"),
                _author_payload(author_b.id, "Author B"),
                _author_payload(author_c.id, "Author C"),
            ],
            "filters": {
                "from_year": 2021,
                "to_year": 2023,
                "sources": ["openalex"],
                "venues": ["physical review a"],
                "grant_numbers": [],
            },
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["metrics"]["total_unique_publications"] == 3
    assert payload["metrics"]["multi_selected_author_publications"] == 3
    assert payload["metrics"]["all_selected_author_publications"] == 1
    assert payload["metrics"]["total_citations"] == 40
    assert payload["participation"]["selected_author_counts"] == [
        {"selected_author_count": 2, "publication_count": 2},
        {"selected_author_count": 3, "publication_count": 1},
    ]
    assert payload["collaboration_by_year"] == [
        {
            "year": 2021,
            "publication_count": 2,
            "percentage_of_year_total": 100.0,
        },
        {
            "year": 2023,
            "publication_count": 1,
            "percentage_of_year_total": 100.0,
        },
    ]
    assert payload["citation_activity"] == [
        {
            "year": 2021,
            "publication_count": 2,
            "citation_count": 10,
            "cumulative_citations": 10,
        },
        {
            "year": 2023,
            "publication_count": 1,
            "citation_count": 30,
            "cumulative_citations": 40,
        },
    ]
    assert payload["top_journals"] == [
        {
            "venue": "Physical Review A",
            "publication_count": 3,
            "citation_count": 40,
            "issn": None,
            "journal_metrics": None,
        }
    ]


@pytest.mark.asyncio
async def test_excluded_work_disappears_from_dashboard_aggregates(session_factory):
    async with session_factory() as session:
        author_a, author_b, author_c = await _seed_three_author_insights_fixture(session)
        excluded = (
            await session.execute(
                select(CanonicalWork).where(CanonicalWork.title == "AB One")
            )
        ).scalar_one()

    response = client.post(
        "/api/analysis/authors/insights",
        json={
            "authors": [
                _author_payload(author_a.id, "Author A"),
                _author_payload(author_b.id, "Author B"),
                _author_payload(author_c.id, "Author C"),
            ],
            "excluded_work_ids": [str(excluded.id)],
        },
    )

    assert response.status_code == 200
    payload = response.json()
    combinations = {row["label"]: row["publication_count"] for row in payload["combinations"]}
    assert payload["metrics"]["total_unique_publications"] == 5
    assert payload["metrics"]["multi_selected_author_publications"] == 4
    assert payload["metrics"]["total_citations"] == 55
    assert combinations["Author A + Author B"] == 2
    assert combinations["Author A + Author C"] == 2
    assert combinations["Author B + Author C"] == 2
    assert combinations["Author A + Author B + Author C"] == 1
    assert payload["collaboration_by_year"][0] == {
        "year": 2021,
        "publication_count": 1,
        "percentage_of_year_total": 50.0,
    }
    assert payload["top_journals"][0] == {
        "venue": "Physical Review A",
        "publication_count": 2,
        "citation_count": 30,
        "issn": None,
        "journal_metrics": None,
    }


@pytest.mark.asyncio
async def test_excluded_abc_work_changes_every_applicable_combination(session_factory):
    async with session_factory() as session:
        author_a, author_b, author_c = await _seed_three_author_insights_fixture(session)
        excluded = (
            await session.execute(
                select(CanonicalWork).where(CanonicalWork.title == "ABC With Extra Coauthor")
            )
        ).scalar_one()

    response = client.post(
        "/api/analysis/authors/insights",
        json={
            "authors": [
                _author_payload(author_a.id, "Author A"),
                _author_payload(author_b.id, "Author B"),
                _author_payload(author_c.id, "Author C"),
            ],
            "excluded_work_ids": [str(excluded.id), str(uuid.uuid4()), "not-a-uuid"],
        },
    )

    assert response.status_code == 200
    payload = response.json()
    combinations = {row["label"]: row["publication_count"] for row in payload["combinations"]}
    assert payload["metrics"]["total_unique_publications"] == 5
    assert payload["metrics"]["all_selected_author_publications"] == 0
    assert payload["metrics"]["total_citations"] == 35
    assert combinations == {
        "Author A + Author B": 2,
        "Author A + Author C": 1,
        "Author B + Author C": 1,
        "Author A + Author B + Author C": 0,
    }


@pytest.mark.asyncio
async def test_excluded_institution_work_is_removed_from_institution_aggregates(
    session_factory,
):
    async with session_factory() as session:
        author_a, author_b, author_c, _author_d = await _seed_institution_insights_fixture(session)
        excluded = (
            await session.execute(
                select(CanonicalWork).where(CanonicalWork.title == "ABC Three Institutions")
            )
        ).scalar_one()

    response = client.post(
        "/api/analysis/authors/insights",
        json={
            "authors": [
                _author_payload(author_a.id, "Author A"),
                _author_payload(author_b.id, "Author B"),
                _author_payload(author_c.id, "Author C"),
            ],
            "excluded_work_ids": [str(excluded.id)],
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["metrics"]["total_unique_publications"] == 4
    assert payload["metrics"]["multi_institution_publications"] == 2
    assert payload["institution_data_quality"]["total_works"] == 4
    assert all(
        row["shared_publication_count"] < 2
        for row in payload["institution_partnerships"]
    )


@pytest.mark.asyncio
async def test_single_author_insights_supports_exclusions_and_yearly_activity(
    session_factory,
):
    async with session_factory() as session:
        author_a, _author_b, _author_c = await _seed_three_author_insights_fixture(session)
        excluded = (
            await session.execute(
                select(CanonicalWork).where(CanonicalWork.title == "A Solo")
            )
        ).scalar_one()

    response = client.post(
        "/api/analysis/authors/insights",
        json={
            "authors": [_author_payload(author_a.id, "Author A")],
            "excluded_work_ids": [str(excluded.id)],
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["combinations"] == []
    assert payload["default_combination_id"] is None
    assert payload["metrics"]["total_unique_publications"] == 4
    assert payload["metrics"]["multi_selected_author_publications"] == 0
    assert payload["collaboration_by_year"] == [
        {
            "year": 2021,
            "publication_count": 2,
            "percentage_of_year_total": 100.0,
        },
        {
            "year": 2022,
            "publication_count": 1,
            "percentage_of_year_total": 100.0,
        },
        {
            "year": 2023,
            "publication_count": 1,
            "percentage_of_year_total": 100.0,
        },
    ]


@pytest.mark.asyncio
async def test_single_author_drilldown_returns_author_publications_with_exclusions(
    session_factory,
):
    async with session_factory() as session:
        author_a, _author_b, _author_c = await _seed_three_author_insights_fixture(session)
        excluded = (
            await session.execute(
                select(CanonicalWork).where(CanonicalWork.title == "A Solo")
            )
        ).scalar_one()

    response = client.post(
        "/api/analysis/authors/insights/publications",
        json={
            "authors": [_author_payload(author_a.id, "Author A")],
            "combination_id": str(author_a.id),
            "excluded_work_ids": [str(excluded.id)],
            "limit": 20,
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["combination_id"] == str(author_a.id)
    assert {row["title"] for row in payload["items"]} == {
        "AB One",
        "AB Two",
        "AC One",
        "ABC With Extra Coauthor",
    }


@pytest.mark.asyncio
async def test_combination_drilldown_ab_returns_shared_works_with_extra_authors(session_factory):
    async with session_factory() as session:
        author_a, author_b, author_c = await _seed_three_author_insights_fixture(session)

    combination_id = stable_author_combination_id([str(author_a.id), str(author_b.id)])
    response = client.post(
        "/api/analysis/authors/insights/publications",
        json={
            "authors": [
                _author_payload(author_a.id, "Author A"),
                _author_payload(author_b.id, "Author B"),
                _author_payload(author_c.id, "Author C"),
            ],
            "combination_id": combination_id,
            "limit": 20,
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["combination_id"] == combination_id
    titles = {row["title"]: row for row in payload["items"]}
    assert set(titles) == {"AB One", "AB Two", "ABC With Extra Coauthor"}
    assert [
        author["display_name"]
        for author in titles["ABC With Extra Coauthor"]["authors"]
    ] == ["Author A", "Author B", "Author C", "Outside Collaborator"]
    assert titles["AB One"]["grants"][0]["award_id"] == "G-1"
    assert titles["AB One"]["providers"] == ["openalex"]
    assert titles["AB One"]["analysis_match"]["verified"] is True


@pytest.mark.asyncio
async def test_excluded_work_does_not_appear_in_combination_drilldown(session_factory):
    async with session_factory() as session:
        author_a, author_b, author_c = await _seed_three_author_insights_fixture(session)
        excluded = (
            await session.execute(
                select(CanonicalWork).where(CanonicalWork.title == "AB One")
            )
        ).scalar_one()

    combination_id = stable_author_combination_id([str(author_a.id), str(author_b.id)])
    response = client.post(
        "/api/analysis/authors/insights/publications",
        json={
            "authors": [
                _author_payload(author_a.id, "Author A"),
                _author_payload(author_b.id, "Author B"),
                _author_payload(author_c.id, "Author C"),
            ],
            "combination_id": combination_id,
            "excluded_work_ids": [str(excluded.id)],
            "filters": {
                "from_year": 2021,
                "to_year": 2023,
                "sources": ["openalex"],
                "venues": [],
                "grant_numbers": [],
            },
        },
    )

    assert response.status_code == 200
    assert [row["title"] for row in response.json()["items"]] == [
        "ABC With Extra Coauthor",
        "AB Two",
    ]


@pytest.mark.asyncio
async def test_exclusions_do_not_delete_or_modify_publications(session_factory):
    async with session_factory() as session:
        author_a, author_b, author_c = await _seed_three_author_insights_fixture(session)
        excluded = (
            await session.execute(
                select(CanonicalWork).where(CanonicalWork.title == "AB One")
            )
        ).scalar_one()
        before = await _table_counts(session)

    response = client.post(
        "/api/analysis/authors/insights",
        json={
            "authors": [
                _author_payload(author_a.id, "Author A"),
                _author_payload(author_b.id, "Author B"),
                _author_payload(author_c.id, "Author C"),
            ],
            "excluded_work_ids": [str(excluded.id)],
        },
    )

    async with session_factory() as session:
        after = await _table_counts(session)
        persisted = (
            await session.execute(
                select(CanonicalWork).where(CanonicalWork.id == excluded.id)
            )
        ).scalar_one()

    assert response.status_code == 200
    assert after == before
    assert persisted.title == "AB One"


@pytest.mark.asyncio
async def test_combination_drilldown_abc_requires_all_three_authors(session_factory):
    async with session_factory() as session:
        author_a, author_b, author_c = await _seed_three_author_insights_fixture(session)

    combination_id = stable_author_combination_id(
        [str(author_a.id), str(author_b.id), str(author_c.id)]
    )
    response = client.post(
        "/api/analysis/authors/insights/publications",
        json={
            "authors": [
                _author_payload(author_a.id, "Author A"),
                _author_payload(author_b.id, "Author B"),
                _author_payload(author_c.id, "Author C"),
            ],
            "combination_id": combination_id,
        },
    )

    assert response.status_code == 200
    assert [row["title"] for row in response.json()["items"]] == [
        "ABC With Extra Coauthor"
    ]


@pytest.mark.asyncio
async def test_combination_drilldown_filters_apply_correctly(session_factory):
    async with session_factory() as session:
        author_a, author_b, author_c = await _seed_three_author_insights_fixture(session)

    combination_id = stable_author_combination_id([str(author_a.id), str(author_b.id)])
    response = client.post(
        "/api/analysis/authors/insights/publications",
        json={
            "authors": [
                _author_payload(author_a.id, "Author A"),
                _author_payload(author_b.id, "Author B"),
                _author_payload(author_c.id, "Author C"),
            ],
            "combination_id": combination_id,
            "filters": {
                "from_year": 2023,
                "to_year": 2023,
                "sources": ["openalex"],
                "venues": ["Physical Review A"],
                "grant_numbers": ["G-2"],
            },
        },
    )

    assert response.status_code == 200
    assert [row["title"] for row in response.json()["items"]] == [
        "ABC With Extra Coauthor"
    ]


@pytest.mark.asyncio
async def test_combination_drilldown_pagination_works(session_factory):
    async with session_factory() as session:
        author_a, author_b, author_c = await _seed_three_author_insights_fixture(session)

    combination_id = stable_author_combination_id([str(author_a.id), str(author_b.id)])
    body = {
        "authors": [
            _author_payload(author_a.id, "Author A"),
            _author_payload(author_b.id, "Author B"),
            _author_payload(author_c.id, "Author C"),
        ],
        "combination_id": combination_id,
        "limit": 2,
    }
    first = client.post("/api/analysis/authors/insights/publications", json=body)
    assert first.status_code == 200
    first_payload = first.json()
    assert len(first_payload["items"]) == 2
    assert first_payload["pagination"]["has_more"] is True

    second = client.post(
        "/api/analysis/authors/insights/publications",
        json={**body, "cursor": first_payload["pagination"]["next_cursor"]},
    )
    assert second.status_code == 200
    second_payload = second.json()
    assert len(second_payload["items"]) == 1
    assert second_payload["pagination"]["has_more"] is False
    assert {
        row["id"] for row in first_payload["items"] + second_payload["items"]
    } == {
        row["id"]
        for row in client.post(
            "/api/analysis/authors/insights/publications",
            json={**body, "limit": 20},
        ).json()["items"]
    }


@pytest.mark.asyncio
async def test_combination_drilldown_deduplicates_canonical_works(session_factory):
    async with session_factory() as session:
        author_a, author_b, _author_c = await _seed_three_author_insights_fixture(session)
        work = (
            await session.execute(
                select(CanonicalWork).where(CanonicalWork.title == "AB One")
            )
        ).scalar_one()
        session.add(
            ProviderWorkRecord(
                id=uuid.uuid4(),
                canonical_work_id=work.id,
                provider="arxiv",
                provider_work_id="2301.00001",
                raw_metadata={"title": "AB One", "publication_year": 2021},
            )
        )
        await session.commit()

    combination_id = stable_author_combination_id([str(author_a.id), str(author_b.id)])
    response = client.post(
        "/api/analysis/authors/insights/publications",
        json={
            "authors": [
                _author_payload(author_a.id, "Author A"),
                _author_payload(author_b.id, "Author B"),
            ],
            "combination_id": combination_id,
        },
    )

    assert response.status_code == 200
    titles = [row["title"] for row in response.json()["items"]]
    assert titles.count("AB One") == 1
    assert next(row for row in response.json()["items"] if row["title"] == "AB One")[
        "providers"
    ] == ["arxiv", "openalex"]


@pytest.mark.asyncio
async def test_combination_drilldown_invalid_combination_id_returns_clean_error(session_factory):
    async with session_factory() as session:
        author_a, author_b, _author_c = await _seed_three_author_insights_fixture(session)

    response = client.post(
        "/api/analysis/authors/insights/publications",
        json={
            "authors": [
                _author_payload(author_a.id, "Author A"),
                _author_payload(author_b.id, "Author B"),
            ],
            "combination_id": "not-a-combination",
        },
    )

    assert response.status_code == 400
    assert "Invalid author combination ID" in response.json()["detail"]


@pytest.mark.asyncio
async def test_combination_drilldown_empty_combination_returns_empty_items(session_factory):
    async with session_factory() as session:
        author_a = await _seed_author(session, name="Author A", openalex_id="A1")
        author_b = await _seed_author(session, name="Author B", openalex_id="A2")
        await _seed_work(
            session,
            title="A Solo Only",
            year=2024,
            provider_work_id="WA-SOLO",
            selected_authors=[author_a],
        )
        await _seed_work(
            session,
            title="B Solo Only",
            year=2024,
            provider_work_id="WB-SOLO",
            selected_authors=[author_b],
        )
        await session.commit()

    combination_id = stable_author_combination_id([str(author_a.id), str(author_b.id)])
    response = client.post(
        "/api/analysis/authors/insights/publications",
        json={
            "authors": [
                _author_payload(author_a.id, "Author A"),
                _author_payload(author_b.id, "Author B"),
            ],
            "combination_id": combination_id,
        },
    )

    assert response.status_code == 200
    assert response.json()["items"] == []
    assert response.json()["pagination"] == {
        "next_cursor": None,
        "has_more": False,
        "page": 1,
        "offset": 0,
        "limit": 20,
        "total": None,
        "corpus_source": None,
    }


@pytest.mark.asyncio
async def test_combination_drilldown_does_not_call_providers_or_write(session_factory):
    async with session_factory() as session:
        author_a, author_b, _author_c = await _seed_three_author_insights_fixture(session)
        before = await _table_counts(session)

    combination_id = stable_author_combination_id([str(author_a.id), str(author_b.id)])
    with patch(
        "app.services.analysis.author_publications.search_works_by_author_ids",
        new_callable=AsyncMock,
    ) as mock_oa:
        response = client.post(
            "/api/analysis/authors/insights/publications",
            json={
                "authors": [
                    _author_payload(author_a.id, "Author A"),
                    _author_payload(author_b.id, "Author B"),
                ],
                "combination_id": combination_id,
            },
        )

    async with session_factory() as session:
        after = await _table_counts(session)

    assert response.status_code == 200
    mock_oa.assert_not_awaited()
    assert after == before


@pytest.mark.asyncio
async def test_institution_collaboration_aggregations_are_real(session_factory):
    async with session_factory() as session:
        author_a, author_b, author_c, author_d = await _seed_institution_insights_fixture(session)

    response = client.post(
        "/api/analysis/authors/insights",
        json={
            "authors": [
                _author_payload(author_a.id, "Author A"),
                _author_payload(author_b.id, "Author B"),
                _author_payload(author_c.id, "Author C"),
                _author_payload(author_d.id, "Author D"),
            ]
        },
    )

    assert response.status_code == 200
    payload = response.json()

    assert payload["metrics"]["total_unique_publications"] == 6
    assert payload["metrics"]["multi_institution_publications"] == 3
    assert payload["participation"]["institution_counts"] == [
        {"institution_count": 1, "publication_count": 2},
        {"institution_count": 2, "publication_count": 2},
        {"institution_count": 3, "publication_count": 1},
    ]
    assert payload["institution_data_quality"] == {
        "total_works": 6,
        "works_with_any_institution": 5,
        "works_without_institution": 1,
        "works_with_partial_institution": 1,
        "works_with_complete_institution": 4,
        "works_with_multi_institution": 3,
    }

    partnerships = {
        (
            row["institution_a"]["id"],
            row["institution_b"]["id"],
        ): row
        for row in payload["institution_partnerships"]
    }
    paper_beta_key = tuple(sorted(["I-PAPER", "I-BETA"]))
    assert paper_beta_key in partnerships
    paper_beta = partnerships[paper_beta_key]
    assert paper_beta["institution_a"] == {
        "id": "I-BETA",
        "name": "Beta University",
        "country": "UK",
    }
    assert paper_beta["institution_b"] == {
        "id": "I-PAPER",
        "name": "Paper University",
        "country": "US",
    }
    assert paper_beta["shared_publication_count"] == 2
    assert paper_beta["selected_author_ids"] == [
        str(author_a.id),
        str(author_b.id),
        str(author_c.id),
    ]
    assert paper_beta["selected_author_names"] == ["Author A", "Author B", "Author C"]

    assert tuple(sorted(["I-BETA", "I-GAMMA"])) in partnerships
    assert tuple(sorted(["I-GAMMA", "I-PAPER"])) in partnerships
    assert tuple(sorted(["I-GAMMA", "I-PROFILE-A"])) in partnerships

    nodes = {row["id"]: row for row in payload["institution_network"]["nodes"]}
    assert nodes["I-PAPER"]["publication_count"] == 3
    assert nodes["I-BETA"]["publication_count"] == 2
    assert nodes["I-GAMMA"]["publication_count"] == 2
    assert nodes["I-PROFILE-A"]["publication_count"] == 1

    edges = {
        (row["source"], row["target"]): row["shared_publication_count"]
        for row in payload["institution_network"]["edges"]
    }
    assert edges[("I-BETA", "I-PAPER")] == 2
    assert all("source" in row and "target" in row for row in payload["institution_network"]["edges"])

    combinations = {row["label"]: row for row in payload["combinations"]}
    assert combinations["Author A + Author B"]["institution_count"] == 4


@pytest.mark.asyncio
async def test_institution_filters_apply_before_aggregation(session_factory):
    async with session_factory() as session:
        author_a, author_b, author_c, _author_d = await _seed_institution_insights_fixture(session)

    response = client.post(
        "/api/analysis/authors/insights",
        json={
            "authors": [
                _author_payload(author_a.id, "Author A"),
                _author_payload(author_b.id, "Author B"),
                _author_payload(author_c.id, "Author C"),
            ],
            "filters": {
                "from_year": 2024,
                "to_year": 2024,
                "sources": ["openalex"],
                "venues": [],
                "grant_numbers": [],
            },
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["metrics"]["total_unique_publications"] == 2
    assert payload["metrics"]["multi_institution_publications"] == 1
    assert payload["participation"]["institution_counts"] == [
        {"institution_count": 1, "publication_count": 1},
        {"institution_count": 3, "publication_count": 1},
    ]
    assert payload["institution_data_quality"]["works_with_any_institution"] == 2
    assert payload["institution_partnerships"][0]["shared_publication_count"] == 1
    assert payload["institution_network"]["edges"]


@pytest.mark.asyncio
async def test_duplicate_provider_records_do_not_create_duplicate_works(session_factory):
    async with session_factory() as session:
        author = await _seed_author(session, name="Katherine Johnson", openalex_id="A1")
        work = await _seed_work(
            session,
            title="Orbital Mechanics",
            year=2020,
            provider_work_id="W1",
            selected_authors=[author],
        )
        provider_record = (
            await session.execute(select(ProviderAuthorRecord).where(
                ProviderAuthorRecord.canonical_author_id == author.id
            ))
        ).scalar_one()
        session.add(
            AuthorWork(
                id=uuid.uuid4(),
                provider_author_record_id=provider_record.id,
                work_id="W1",
                work_id_type="openalex",
                title="Orbital Mechanics",
                publication_year=2020,
            )
        )
        await session.commit()

        mapping = await AuthorInsightsService(session)._load_work_membership([str(author.id)])

    assert list(mapping.keys()) == [str(work.id)]
    assert mapping[str(work.id)] == {str(author.id)}


@pytest.mark.asyncio
async def test_filters_are_accepted_in_dashboard_contract(session_factory):
    async with session_factory() as session:
        author = await _seed_author(session, name="Rosalind Franklin", openalex_id="A1")
        await _seed_work(
            session,
            title="Included",
            year=2024,
            provider_work_id="W1",
            selected_authors=[author],
            venue="Nature",
        )
        await _seed_work(
            session,
            title="Excluded",
            year=2018,
            provider_work_id="W2",
            selected_authors=[author],
            venue="Science",
        )
        await session.commit()

    response = client.post(
        "/api/analysis/authors/insights",
        json={
            "authors": [_author_payload(author.id, "Rosalind Franklin")],
            "filters": {
                "from_year": 2020,
                "to_year": 2026,
                "sources": ["openalex"],
                "venues": ["Nature"],
                "grant_numbers": [],
            },
        },
    )

    assert response.status_code == 200
    assert response.json()["metrics"]["total_unique_publications"] == 1


@pytest.mark.asyncio
async def test_endpoint_returns_complete_dashboard_response_shape(session_factory):
    async with session_factory() as session:
        author = await _seed_author(session, name="Chien-Shiung Wu", openalex_id="A1")
        await session.commit()

    response = client.post(
        "/api/analysis/authors/insights",
        json={"authors": [_author_payload(author.id, "Chien-Shiung Wu")]},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["combination_mode"] == "all_combinations"
    assert set(payload.keys()) == {
        "authors",
        "metrics",
        "combinations",
        "combination_mode",
        "collaboration_by_year",
        "participation",
        "institution_network",
        "institution_partnerships",
        "citation_activity",
        "top_journals",
        "default_combination_id",
        "institution_data_quality",
        "facets",
        "coverage",
        "enrichment",
    }
    assert payload["coverage"]["corpus_complete"] is True
    assert payload["coverage"]["enrichment_affects_completeness"] is False
    assert payload["enrichment"] is not None
    assert set(payload["metrics"].keys()) == {
        "total_unique_publications",
        "multi_selected_author_publications",
        "all_selected_author_publications",
        "multi_institution_publications",
        "total_citations",
        "average_citations",
    }
    assert payload["institution_network"] == {"nodes": [], "edges": []}
    assert payload["facets"] == {
        "sources": [],
        "institutions": [],
        "venues": [],
        "grants": [],
        "authors": [],
    }


@pytest.mark.asyncio
async def test_empty_store_returns_empty_facets_without_provider_http(session_factory):
    async with session_factory() as session:
        author = await _seed_author(session, name="Empty Store", openalex_id="A1")
        await session.commit()

    with patch(
        "app.services.analysis.author_publications.search_works_by_author_ids",
        new_callable=AsyncMock,
    ) as mock_oa, patch(
        "app.services.analysis.author_publications.search_arxiv_publications_by_authors",
        new_callable=AsyncMock,
    ) as mock_arxiv, patch(
        "app.services.analysis.author_work_sync.search_works_by_author_ids",
        new_callable=AsyncMock,
    ) as mock_sync:
        response = client.post(
            "/api/analysis/authors/insights",
            json={"authors": [_author_payload(author.id, "Empty Store")]},
        )

    assert response.status_code == 200
    payload = response.json()
    assert payload["metrics"]["total_unique_publications"] == 0
    assert payload["facets"]["sources"] == []
    assert payload["facets"]["institutions"] == []
    assert payload["facets"]["venues"] == []
    assert payload["facets"]["grants"] == []
    assert payload["facets"]["authors"] == []
    mock_oa.assert_not_awaited()
    mock_arxiv.assert_not_awaited()
    mock_sync.assert_not_awaited()


@pytest.mark.asyncio
async def test_stored_works_populate_insights_facets_without_provider_http(session_factory):
    async with session_factory() as session:
        author = await _seed_author(session, name="Stored Author", openalex_id="A1")
        await _seed_work(
            session,
            title="Stored Nature Paper",
            year=2024,
            provider_work_id="W1",
            selected_authors=[author],
            venue="Nature",
            grant_number="R01GM123456",
        )
        await session.commit()

    with patch(
        "app.services.analysis.author_publications.search_works_by_author_ids",
        new_callable=AsyncMock,
    ) as mock_oa, patch(
        "app.services.analysis.author_publications.search_arxiv_publications_by_authors",
        new_callable=AsyncMock,
    ) as mock_arxiv:
        response = client.post(
            "/api/analysis/authors/insights",
            json={"authors": [_author_payload(author.id, "Stored Author")]},
        )

    assert response.status_code == 200
    payload = response.json()
    assert payload["metrics"]["total_unique_publications"] == 1
    assert any(row["value"] == "openalex" for row in payload["facets"]["sources"])
    assert any(row.get("label") == "Nature" or row.get("value") == "nature" for row in payload["facets"]["venues"])
    mock_oa.assert_not_awaited()
    mock_arxiv.assert_not_awaited()


def test_existing_author_publications_endpoint_behavior_is_unchanged(monkeypatch):
    monkeypatch.setenv("WORK_PERSISTENCE_ENABLED", "false")
    monkeypatch.setenv("AUTHOR_RESOLUTION_ENABLED", "false")
    monkeypatch.setenv("PROVIDER_SEARCH_CACHE_ENABLED", "false")
    monkeypatch.setenv("OPENALEX_API_KEY", "test-key")
    monkeypatch.setenv("ARXIV_ENABLED", "false")
    get_settings.cache_clear()
    with patch(
        "app.services.analysis.author_publications.search_works_by_author_ids",
        new_callable=AsyncMock,
    ) as mock_oa:
        mock_oa.return_value = {
            "results": [
                {
                    "result_id": "openalex:W1",
                    "result_type": "work",
                    "openalex_id": "W1",
                    "title": "Publication Endpoint Paper",
                    "authors": [{"name": "Jane Doe"}],
                    "publication_year": 2024,
                    "source": "openalex",
                    "grants": [],
                }
            ],
            "next_cursor": None,
            "has_more": False,
        }

        response = client.post(
            "/api/analysis/authors/publications",
            json={
                "authors": [
                    {
                        "canonical_author_id": "author-1",
                        "provider": "openalex",
                        "provider_author_id": "A1234567890",
                        "display_name": "Jane Doe",
                    }
                ],
                "limit": 20,
                "cursor": None,
            },
        )

    assert response.status_code == 200
    assert response.json()["items"][0]["title"] == "Publication Endpoint Paper"
    assert mock_oa.await_count == 1
    get_settings.cache_clear()


@pytest.mark.asyncio
async def test_author_insights_does_not_introduce_persistence_writes(session_factory):
    async with session_factory() as session:
        author = await _seed_author(session, name="No Writes", openalex_id="A1")
        await _seed_work(
            session,
            title="Stored Only",
            year=2025,
            provider_work_id="W1",
            selected_authors=[author],
        )
        await session.commit()
        before = await _table_counts(session)

    with patch(
        "app.services.analysis.author_publications.search_works_by_author_ids",
        new_callable=AsyncMock,
    ) as mock_oa:
        response = client.post(
            "/api/analysis/authors/insights",
            json={"authors": [_author_payload(author.id, "No Writes")]},
        )

    async with session_factory() as session:
        after = await _table_counts(session)

    assert response.status_code == 200
    mock_oa.assert_not_awaited()
    assert after == before


@pytest.mark.asyncio
async def test_existing_provider_record_short_circuit_preserves_sqlite_locking_fix(session_factory):
    async with session_factory() as session:
        service = WorkPersistenceService(session)
        first_candidate = candidate_from_provider_result(
            {
                "result_id": "openalex:WLOCK",
                "result_type": "work",
                "openalex_id": "WLOCK",
                "title": "Locking Fix Paper",
                "publication_year": 2024,
                "authors": [{"id": "A1", "name": "Jane Doe"}],
            },
            provider="openalex",
        )
        canonical, created = await service.resolve_candidate(first_candidate)
        await session.commit()
        assert created is True

        second_candidate = candidate_from_provider_result(
            {
                "result_id": "openalex:WLOCK",
                "result_type": "work",
                "openalex_id": "WLOCK",
                "title": "Locking Fix Paper Updated",
                "publication_year": 2025,
                "authors": [{"id": "A2", "name": "Changed Author"}],
            },
            provider="openalex",
        )
        again, created_again = await service.resolve_candidate(second_candidate)
        await session.commit()

        record = (
            await session.execute(
                select(ProviderWorkRecord).where(
                    ProviderWorkRecord.provider == "openalex",
                    ProviderWorkRecord.provider_work_id == "WLOCK",
                )
            )
        ).scalar_one()
        authorship_count = (
            await session.execute(
                select(func.count(WorkAuthorship.id)).where(
                    WorkAuthorship.canonical_work_id == canonical.id
                )
            )
        ).scalar_one()

    assert again.id == canonical.id
    assert created_again is False
    # Existing provider-work short-circuit may refresh raw metadata, but must not
    # recreate authorship rows (the historical SQLite locking failure mode).
    assert record.raw_metadata["title"] == "Locking Fix Paper Updated"
    assert authorship_count == 1


async def _table_counts(session: AsyncSession) -> dict[str, int]:
    return {
        "canonical_works": (
            await session.execute(select(func.count(CanonicalWork.id)))
        ).scalar_one(),
        "provider_work_records": (
            await session.execute(select(func.count(ProviderWorkRecord.id)))
        ).scalar_one(),
        "work_authorships": (
            await session.execute(select(func.count(WorkAuthorship.id)))
        ).scalar_one(),
        "work_grant_matches": (
            await session.execute(select(func.count(WorkGrantMatch.id)))
        ).scalar_one(),
    }
