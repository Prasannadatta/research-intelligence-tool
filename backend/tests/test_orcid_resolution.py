"""ORCID-aware canonical author resolution tests."""

from __future__ import annotations

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.db.base import Base
from app.services.author_resolution.candidate import (
    AuthorCandidate,
    InstitutionRef,
    WorkRef,
    candidate_from_provider_result,
    linked_openalex_id_from_orcid_metadata,
)
from app.services.author_resolution.scoring import (
    DECISION_AUTO_MERGE,
    DECISION_SEPARATE,
    score_candidate_pair,
)
from app.services.author_resolution.service import AuthorResolutionService, resolve_author_page

LIN_BERKELEY = "0000-0001-6860-9566"
LIN_EDUCATION = "0000-0002-2400-5864"


@pytest_asyncio.fixture
async def session():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    async with factory() as db:
        yield db
    await engine.dispose()


def _orcid_search_row(
    orcid: str,
    *,
    institution: str,
    doi: str | None = None,
    works_count: int = 1,
    start_date: str = "2020",
    external_ids: list[dict] | None = None,
) -> dict:
    works = []
    if doi:
        works.append(
            {
                "id": doi,
                "id_type": "doi",
                "title": "Sample",
                "publication_year": 2024,
            }
        )
    return {
        "result_id": f"orcid:{orcid}",
        "result_type": "author",
        "source": "orcid",
        "display_name": "Lin Lin",
        "orcid": orcid,
        "works_count": works_count,
        "primary_institution": {"name": institution, "country_code": "US"},
        "institutions": [{"name": institution, "country_code": "US"}],
        "employments": [
            {
                "name": institution,
                "country_code": "US",
                "role": "Professor",
                "start_date": start_date,
                "end_date": None,
            }
        ],
        "external_ids": external_ids or [],
        "works": works,
    }


def _enriched_orcid_search_row(
    orcid: str,
    openalex_id: str,
    *,
    institution: str,
    doi: str | None = None,
    works_count: int = 1,
) -> dict:
    row = _orcid_search_row(
        orcid,
        institution=institution,
        doi=doi,
        works_count=works_count,
    )
    row["openalex_id"] = openalex_id
    row["source_records"] = [
        {"provider": "orcid", "provider_author_id": orcid},
        {"provider": "openalex", "provider_author_id": openalex_id},
    ]
    return row


def _to_analysis_author_payload(item: dict) -> dict | None:
    source_records = item.get("source_records") or []
    openalex = next((row for row in source_records if row.get("provider") == "openalex"), None)
    arxiv = next((row for row in source_records if row.get("provider") == "arxiv"), None)
    provider = (
        (openalex or {}).get("provider")
        or (arxiv or {}).get("provider")
        or item.get("source")
    )
    provider_author_id = (
        (openalex or {}).get("provider_author_id")
        or (arxiv or {}).get("provider_author_id")
        or item.get("openalex_id")
    )
    if not provider or not provider_author_id:
        if item.get("openalex_id"):
            provider, provider_author_id = "openalex", item["openalex_id"]
    canonical_author_id = (
        item.get("id") or item.get("result_id") or item.get("canonical_author_id")
    )
    display_name = item.get("display_name") or ""
    if not canonical_author_id or not provider or not provider_author_id or not display_name:
        return None
    return {
        "canonical_author_id": str(canonical_author_id),
        "provider": str(provider).lower(),
        "provider_author_id": str(provider_author_id),
        "display_name": str(display_name).strip(),
    }


def test_linked_openalex_id_requires_exact_orcid_metadata():
    enriched = _enriched_orcid_search_row(
        LIN_BERKELEY,
        "A501",
        institution="University of California Berkeley",
    )
    assert (
        linked_openalex_id_from_orcid_metadata(
            orcid=LIN_BERKELEY,
            raw_metadata=enriched,
        )
        == "A501"
    )
    plain = _orcid_search_row(LIN_BERKELEY, institution="UC Berkeley")
    assert linked_openalex_id_from_orcid_metadata(orcid=LIN_BERKELEY, raw_metadata=plain) is None
    name_only_openalex = {
        "result_id": "openalex:A999",
        "source": "openalex",
        "openalex_id": "A999",
        "display_name": "Lin Lin",
        "orcid": None,
    }
    assert (
        linked_openalex_id_from_orcid_metadata(
            orcid=LIN_BERKELEY,
            raw_metadata=name_only_openalex,
        )
        is None
    )


@pytest.mark.asyncio
async def test_enriched_orcid_search_row_preserves_openalex_provider_record(session):
    service = AuthorResolutionService(session)
    enriched = _enriched_orcid_search_row(
        LIN_BERKELEY,
        "A501",
        institution="University of California Berkeley",
        doi="10.1038/s41567-026-03389-y",
        works_count=83,
    )
    candidate = candidate_from_provider_result(enriched)
    assert candidate is not None
    resolved, created = await service.resolve_candidate(candidate)
    await session.commit()
    assert created is True
    assert resolved["orcid"] == LIN_BERKELEY
    assert resolved["openalex_id"] == "A501"
    assert resolved["source"] == "openalex"
    providers = {row["provider"]: row["provider_author_id"] for row in resolved["source_records"]}
    assert providers == {"orcid": LIN_BERKELEY, "openalex": "A501"}
    payload = _to_analysis_author_payload(resolved)
    assert payload == {
        "canonical_author_id": resolved["id"],
        "provider": "openalex",
        "provider_author_id": "A501",
        "display_name": "Lin Lin",
    }


@pytest.mark.asyncio
async def test_all_sources_style_enriched_rows_keep_both_provider_records(session):
    page = await resolve_author_page(
        session,
        [
            _enriched_orcid_search_row(
                LIN_BERKELEY,
                "A9",
                institution="University of California Berkeley",
                works_count=83,
            ),
            _orcid_search_row(
                LIN_EDUCATION,
                institution="Shanghai Normal University",
                works_count=2,
            ),
        ],
    )
    assert len(page["results"]) == 2
    by_orcid = {row["orcid"]: row for row in page["results"]}
    berkeley = by_orcid[LIN_BERKELEY]
    education = by_orcid[LIN_EDUCATION]
    assert berkeley["openalex_id"] == "A9"
    assert {row["provider"] for row in berkeley["source_records"]} == {"orcid", "openalex"}
    assert education["openalex_id"] is None
    assert {row["provider"] for row in education["source_records"]} == {"orcid"}
    assert berkeley["id"] != education["id"]
    assert _to_analysis_author_payload(berkeley)["provider_author_id"] == "A9"
    assert _to_analysis_author_payload(education) is None


@pytest.mark.asyncio
async def test_orcid_row_without_openalex_link_stays_orcid_only(session):
    service = AuthorResolutionService(session)
    candidate = candidate_from_provider_result(
        _orcid_search_row(LIN_EDUCATION, institution="Shanghai Normal University")
    )
    resolved, _ = await service.resolve_candidate(candidate)
    await session.commit()
    assert resolved["orcid"] == LIN_EDUCATION
    assert resolved["openalex_id"] is None
    assert resolved["source_records"] == [
        {"provider": "orcid", "provider_author_id": LIN_EDUCATION}
    ]


def test_exact_orcid_match_is_strong_identity_signal():
    left = AuthorCandidate(
        provider="openalex",
        provider_author_id="A1",
        display_name="L. Lin",
        orcid=LIN_BERKELEY,
    )
    right = AuthorCandidate(
        provider="orcid",
        provider_author_id=LIN_BERKELEY,
        display_name="Lin Lin",
        orcid=LIN_BERKELEY,
    )
    score = score_candidate_pair(
        left,
        right,
        auto_merge_threshold=85,
        possible_duplicate_threshold=60,
    )
    assert score.decision == DECISION_AUTO_MERGE
    assert "same_orcid" in score.reasoning["signals"]


def test_name_alone_does_not_auto_merge_orcid_and_openalex():
    left = AuthorCandidate(
        provider="openalex",
        provider_author_id="A1",
        display_name="Lin Lin",
    )
    right = AuthorCandidate(
        provider="orcid",
        provider_author_id=LIN_EDUCATION,
        display_name="Lin Lin",
        orcid=LIN_EDUCATION,
        institutions=[InstitutionRef(name="Shanghai Normal University")],
    )
    score = score_candidate_pair(
        left,
        right,
        auto_merge_threshold=85,
        possible_duplicate_threshold=60,
    )
    assert score.decision != DECISION_AUTO_MERGE


def test_doi_overlap_supports_identity_without_orcid_on_openalex():
    left = AuthorCandidate(
        provider="openalex",
        provider_author_id="A9",
        display_name="Lin Lin",
        works=[WorkRef(id="https://doi.org/10.1038/s41567-026-03389-y", id_type="doi")],
    )
    right = AuthorCandidate(
        provider="orcid",
        provider_author_id=LIN_BERKELEY,
        display_name="Lin Lin",
        orcid=LIN_BERKELEY,
        works=[WorkRef(id="10.1038/s41567-026-03389-y", id_type="doi")],
    )
    score = score_candidate_pair(
        left,
        right,
        auto_merge_threshold=85,
        possible_duplicate_threshold=60,
    )
    assert score.decision == DECISION_AUTO_MERGE
    assert "shared_works" in score.reasoning["signals"]


@pytest.mark.asyncio
async def test_exact_orcid_links_orcid_record_to_existing_canonical(session):
    service = AuthorResolutionService(session)
    openalex, _ = await service.resolve_candidate(
        AuthorCandidate(
            provider="openalex",
            provider_author_id="A5107195431",
            display_name="Lin Lin",
            orcid=LIN_BERKELEY,
            institutions=[InstitutionRef(id="I95457486", name="University of California, Berkeley")],
        )
    )
    orcid, _ = await service.resolve_candidate(
        AuthorCandidate(
            provider="orcid",
            provider_author_id=LIN_BERKELEY,
            display_name="Lin Lin",
            orcid=LIN_BERKELEY,
            institutions=[InstitutionRef(name="University of California Berkeley")],
            works=[WorkRef(id="10.1038/s41567-026-03389-y", id_type="doi")],
            works_count=83,
            raw_metadata={
                "employments": [
                    {
                        "name": "University of California Berkeley",
                        "role": "Professor",
                        "start_date": "2014",
                        "end_date": None,
                    }
                ],
                "external_ids": [],
            },
        )
    )
    await session.commit()
    assert openalex["id"] == orcid["id"]
    assert orcid["orcid"] == LIN_BERKELEY
    providers = {row["provider"] for row in orcid["source_records"]}
    assert providers == {"openalex", "orcid"}


@pytest.mark.asyncio
async def test_openalex_author_with_same_orcid_is_enriched(session):
    service = AuthorResolutionService(session)
    await service.resolve_candidate(
        AuthorCandidate(
            provider="openalex",
            provider_author_id="A111",
            display_name="Lin Lin",
            orcid=LIN_BERKELEY,
            institutions=[
                InstitutionRef(
                    id="I95457486",
                    name="Department of Mathematics, University of California, Berkeley",
                )
            ],
            works_count=40,
        )
    )
    enriched, _ = await service.resolve_candidate(
        AuthorCandidate(
            provider="orcid",
            provider_author_id=LIN_BERKELEY,
            display_name="Lin Lin",
            orcid=LIN_BERKELEY,
            institutions=[InstitutionRef(name="California Institute of Technology")],
            works=[WorkRef(id="10.1137/25M1806120", id_type="doi", title="QSP")],
            works_count=83,
            raw_metadata={
                "employments": [
                    {
                        "name": "California Institute of Technology",
                        "role": "Professor",
                        "department": "Computing and Mathematical Sciences",
                        "start_date": "2026-07-01",
                        "end_date": None,
                    }
                ],
                "external_ids": [
                    {"type": "Scopus Author ID", "value": "999"}
                ],
            },
        )
    )
    await session.commit()
    assert enriched["orcid"] == LIN_BERKELEY
    assert enriched["openalex_id"] == "A111"
    assert enriched["works_count"] == 83
    names = [inst["name"] for inst in enriched["institutions"]]
    assert names[0] == "Department of Mathematics, University of California, Berkeley"
    assert "California Institute of Technology" in names
    assert enriched["employments"][0]["start_date"] == "2026-07-01"
    assert enriched["external_ids"][0]["value"] == "999"
    assert enriched["works"][0]["id"] == "doi:10.1137/25m1806120"


@pytest.mark.asyncio
async def test_doi_overlap_links_orcid_without_openalex_orcid_field(session):
    service = AuthorResolutionService(session)
    first, _ = await service.resolve_candidate(
        AuthorCandidate(
            provider="openalex",
            provider_author_id="A222",
            display_name="Lin Lin",
            works=[WorkRef(id="10.1016/j.jcp.2024.113351", id_type="doi")],
        )
    )
    second, _ = await service.resolve_candidate(
        AuthorCandidate(
            provider="orcid",
            provider_author_id=LIN_BERKELEY,
            display_name="Lin Lin",
            orcid=LIN_BERKELEY,
            works=[WorkRef(id="doi:10.1016/j.jcp.2024.113351", id_type="doi")],
        )
    )
    await session.commit()
    assert first["id"] == second["id"]
    assert second["orcid"] == LIN_BERKELEY


@pytest.mark.asyncio
async def test_ambiguous_lin_lin_orcid_profiles_remain_separate(session):
    page = await resolve_author_page(
        session,
        [
            _orcid_search_row(
                LIN_BERKELEY,
                institution="University of California Berkeley",
                doi="10.1038/s41567-026-03389-y",
                works_count=83,
            ),
            _orcid_search_row(
                LIN_EDUCATION,
                institution="Shanghai Normal University",
                doi="10.1016/j.tsc.2023.101450",
                works_count=2,
            ),
        ],
    )
    assert len(page["results"]) == 2
    ids = {row["id"] for row in page["results"]}
    orcids = {row["orcid"] for row in page["results"]}
    assert len(ids) == 2
    assert orcids == {LIN_BERKELEY, LIN_EDUCATION}
    providers = {
        row["orcid"]: {src["provider"] for src in row["source_records"]}
        for row in page["results"]
    }
    assert providers[LIN_BERKELEY] == {"orcid"}
    assert providers[LIN_EDUCATION] == {"orcid"}


@pytest.mark.asyncio
async def test_name_only_openalex_and_orcid_lin_lin_stay_separate(session):
    page = await resolve_author_page(
        session,
        [
            {
                "result_type": "author",
                "source": "openalex",
                "openalex_id": "A999",
                "display_name": "Lin Lin",
                "primary_institution": {"name": "Some University"},
            },
            _orcid_search_row(
                LIN_EDUCATION,
                institution="Shanghai Normal University",
                works_count=2,
            ),
        ],
    )
    assert len(page["results"]) == 2
    assert {row["id"] for row in page["results"]}.__len__() == 2
    by_source = {row["source"]: row for row in page["results"]}
    assert "openalex" in by_source
    assert "orcid" in by_source
    assert by_source["openalex"]["orcid"] is None
    assert by_source["orcid"]["orcid"] == LIN_EDUCATION


def test_candidate_mapping_keeps_orcid_as_provider_id():
    candidate = candidate_from_provider_result(
        _orcid_search_row(LIN_BERKELEY, institution="UC Berkeley", doi="10.1/abc")
    )
    assert candidate is not None
    assert candidate.provider == "orcid"
    assert candidate.provider_author_id == LIN_BERKELEY
    assert candidate.orcid == LIN_BERKELEY
    assert candidate.works[0].id == "doi:10.1/abc"
