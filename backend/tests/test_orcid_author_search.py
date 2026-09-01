"""Live author-search wiring for ORCID alongside OpenAlex and arXiv."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient

from app.core.config import get_settings
from app.integrations.orcid.client import OrcidApiError
from app.main import app
from app.services.author_resolution.candidate import AuthorCandidate, InstitutionRef, WorkRef

client = TestClient(app)

LIN_A = "0000-0001-6860-9566"
LIN_B = "0000-0002-2400-5864"
HEAD_GORDON = "0000-0002-4309-6669"


@pytest.fixture(autouse=True)
def _search_settings(monkeypatch):
    monkeypatch.setenv("AUTHOR_RESOLUTION_ENABLED", "false")
    monkeypatch.setenv("WORK_PERSISTENCE_ENABLED", "false")
    monkeypatch.setenv("PROVIDER_SEARCH_CACHE_ENABLED", "false")
    monkeypatch.setenv("ORCID_ENABLED", "true")

    async def _empty_oa_orcid(**_kwargs):
        return {
            "query": "",
            "entity_type": "authors",
            "source": "openalex",
            "results": [],
            "next_cursor": None,
            "has_more": False,
        }

    monkeypatch.setattr(
        "app.integrations.openalex.unified_search.search_openalex_authors_by_orcid",
        _empty_oa_orcid,
    )
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def _orcid_candidate(
    orcid: str,
    *,
    display_name: str,
    institution: str,
    works_count: int = 1,
    doi: str | None = "10.1000/test",
    start_date: str | None = "2020",
) -> AuthorCandidate:
    works = []
    if doi:
        works.append(WorkRef(id=doi, id_type="doi", title="Sample work", publication_year=2024))
    return AuthorCandidate(
        provider="orcid",
        provider_author_id=orcid,
        display_name=display_name,
        institutions=[InstitutionRef(name=institution, country_code="US")],
        works=works,
        orcid=orcid,
        works_count=works_count,
        raw_metadata={
            "orcid": orcid,
            "given_names": display_name.split(" ")[0],
            "family_name": display_name.split(" ")[-1],
            "employments": [
                {
                    "name": institution,
                    "country_code": "US",
                    "start_date": start_date,
                    "end_date": None,
                    "role": "Professor",
                    "department": "Mathematics",
                }
            ],
            "external_ids": [],
            "dois": [doi] if doi else [],
        },
    )


def test_capabilities_expose_orcid_author_source():
    payload = client.get("/api/search/capabilities").json()
    by_id = {item["id"]: item for item in payload["sources"]}
    assert by_id["orcid"]["enabled"] is True
    assert by_id["orcid"]["supported_entity_types"] == ["authors"]
    assert by_id["orcid"]["label"] == "ORCID"


def test_lin_lin_returns_separate_orcid_candidates():
    async def fake_orcid(**kwargs):
        assert "given-names" in kwargs["query"] or kwargs["query"] == "Lin Lin"
        return {
            "query": 'given-names:"Lin" AND family-name:"Lin"',
            "source": "orcid",
            "results": [
                _orcid_candidate(
                    LIN_A,
                    display_name="Lin Lin",
                    institution="University of California Berkeley",
                    works_count=83,
                    doi="10.1038/s41567-026-03389-y",
                ),
                _orcid_candidate(
                    LIN_B,
                    display_name="Lin Lin",
                    institution="Shanghai Normal University",
                    works_count=2,
                    doi="10.1016/j.tsc.2023.101450",
                ),
            ],
            "num_found": 2,
            "has_more": False,
        }

    with patch(
        "app.services.search.orcid_provider.search_orcid_authors",
        side_effect=fake_orcid,
    ):
        response = client.get(
            "/api/search",
            params={"query": "Lin Lin", "entity_type": "authors", "source": "orcid"},
        )

    assert response.status_code == 200
    rows = response.json()["results"]
    orcids = [row["orcid"] for row in rows]
    assert orcids == [LIN_A, LIN_B]
    assert all(row["source"] == "orcid" for row in rows)
    assert all(row["display_name"] == "Lin Lin" for row in rows)
    assert rows[0]["result_id"] != rows[1]["result_id"]
    assert rows[0]["primary_institution"]["name"] == "University of California Berkeley"
    assert rows[0]["works_count"] == 83
    assert rows[0]["works"][0]["id"] == "10.1038/s41567-026-03389-y"
    assert rows[0]["works"][0]["id_type"] == "doi"


def test_berkeley_affiliation_hint_is_passed_to_orcid_search():
    captured = {}

    async def fake_orcid(**kwargs):
        captured.update(kwargs)
        return {
            "query": kwargs.get("query"),
            "source": "orcid",
            "results": [
                _orcid_candidate(
                    LIN_A,
                    display_name="Lin Lin",
                    institution="University of California Berkeley",
                )
            ],
            "num_found": 1,
            "has_more": False,
        }

    with patch(
        "app.services.search.orcid_provider.search_orcid_authors",
        side_effect=fake_orcid,
    ):
        response = client.get(
            "/api/search",
            params={
                "query": "Lin Lin",
                "entity_type": "authors",
                "source": "orcid",
                "affiliation": "Berkeley",
            },
        )

    assert response.status_code == 200
    assert captured["affiliation"] == "Berkeley"
    assert len(response.json()["results"]) == 1
    assert response.json()["results"][0]["orcid"] == LIN_A


def test_martin_head_gordon_orcid_candidate_appears():
    async def fake_orcid(**kwargs):
        return {
            "query": kwargs.get("query"),
            "source": "orcid",
            "results": [
                _orcid_candidate(
                    HEAD_GORDON,
                    display_name="Martin Head-Gordon",
                    institution="University of California, Berkeley",
                    works_count=195,
                    doi="10.1038/s42005-024-01794-4",
                )
            ],
            "num_found": 1,
            "has_more": False,
        }

    with patch(
        "app.services.search.orcid_provider.search_orcid_authors",
        side_effect=fake_orcid,
    ):
        response = client.get(
            "/api/search",
            params={
                "query": "Martin Head-Gordon",
                "entity_type": "authors",
                "source": "orcid",
            },
        )

    assert response.status_code == 200
    row = response.json()["results"][0]
    assert row["orcid"] == HEAD_GORDON
    assert row["display_name"] == "Martin Head-Gordon"
    assert row["source"] == "orcid"
    assert row["result_id"] == f"orcid:{HEAD_GORDON}"
    assert row["works_count"] == 195


def test_orcid_outage_does_not_break_openalex_or_arxiv():
    openalex_row = {
        "result_id": "openalex:A1",
        "result_type": "author",
        "openalex_id": "A1",
        "display_name": "Lin Lin",
        "source": "openalex",
        "works_count": 10,
    }
    arxiv_row = {
        "result_id": "arxiv-author-name:lin-lin",
        "result_type": "author_name",
        "display_name": "Lin Lin",
        "source": "arxiv",
        "is_verified_profile": False,
    }

    async def boom(**_kwargs):
        raise OrcidApiError("ORCID search is temporarily unavailable.")

    with (
        patch(
            "app.services.search.orcid_provider.search_orcid_authors",
            side_effect=boom,
        ),
        patch(
            "app.services.search.openalex_provider.unified_openalex_search",
            new_callable=AsyncMock,
            return_value={
                "query": "Lin Lin",
                "entity_type": "authors",
                "source": "openalex",
                "results": [openalex_row],
                "next_cursor": None,
                "has_more": False,
            },
        ),
        patch(
            "app.services.search.arxiv_provider.search_arxiv_authors",
            new_callable=AsyncMock,
            return_value={
                "query": "Lin Lin",
                "entity_type": "authors",
                "source": "arxiv",
                "results": [arxiv_row],
                "next_cursor": None,
                "has_more": False,
            },
        ),
    ):
        openalex = client.get(
            "/api/search",
            params={"query": "Lin Lin", "entity_type": "authors", "source": "openalex"},
        )
        arxiv = client.get(
            "/api/search",
            params={"query": "Lin Lin", "entity_type": "authors", "source": "arxiv"},
        )

    assert openalex.status_code == 200
    assert openalex.json()["results"][0]["source"] == "openalex"
    assert openalex.json()["results"][0]["openalex_id"] == "A1"
    assert all(row["source"] != "orcid" for row in openalex.json()["results"])
    assert arxiv.status_code == 200
    assert arxiv.json()["results"][0]["source"] == "arxiv"


def test_openalex_author_search_appends_orcid_without_name_merge():
    async def fake_orcid(**_kwargs):
        return {
            "query": "Lin Lin",
            "source": "orcid",
            "results": [
                _orcid_candidate(
                    LIN_A,
                    display_name="Lin Lin",
                    institution="University of California Berkeley",
                ),
                _orcid_candidate(
                    LIN_B,
                    display_name="Lin Lin",
                    institution="Shanghai Normal University",
                ),
            ],
            "num_found": 2,
            "has_more": False,
        }

    openalex_row = {
        "result_id": "openalex:A9",
        "result_type": "author",
        "openalex_id": "A9",
        "display_name": "Lin Lin",
        "source": "openalex",
        "orcid": LIN_A,
        "works_count": 40,
    }

    with (
        patch(
            "app.services.search.orcid_provider.search_orcid_authors",
            side_effect=fake_orcid,
        ),
        patch(
            "app.services.search.openalex_provider.unified_openalex_search",
            new_callable=AsyncMock,
            return_value={
                "query": "Lin Lin",
                "entity_type": "authors",
                "source": "openalex",
                "results": [openalex_row],
                "next_cursor": None,
                "has_more": False,
            },
        ),
    ):
        response = client.get(
            "/api/search",
            params={"query": "Lin Lin", "entity_type": "authors", "source": "openalex"},
        )

    assert response.status_code == 200
    rows = response.json()["results"]
    sources = [row["source"] for row in rows]
    assert sources == ["orcid", "orcid"]
    by_orcid = {row["orcid"]: row for row in rows}
    assert by_orcid[LIN_A]["openalex_id"] == "A9"
    assert by_orcid[LIN_A]["source"] == "orcid"
    assert by_orcid[LIN_A]["works_count"] == 40
    assert by_orcid[LIN_B].get("openalex_id") in (None, "")
    assert by_orcid[LIN_A]["result_id"] != by_orcid[LIN_B]["result_id"]
    assert by_orcid[LIN_A]["display_name"] == by_orcid[LIN_B]["display_name"] == "Lin Lin"


def test_orcid_id_search_returns_berkeley_profile():
    captured = {}

    async def fake_orcid(**kwargs):
        captured.update(kwargs)
        return {
            "query": kwargs.get("query"),
            "source": "orcid",
            "results": [
                _orcid_candidate(
                    LIN_A,
                    display_name="Lin Lin",
                    institution="University of California Berkeley",
                    works_count=83,
                    doi="10.1038/s41567-026-03389-y",
                )
            ],
            "num_found": 1,
            "has_more": False,
        }

    with patch(
        "app.services.search.orcid_provider.search_orcid_authors",
        side_effect=fake_orcid,
    ):
        response = client.get(
            "/api/search",
            params={
                "query": LIN_A,
                "entity_type": "authors",
                "source": "orcid",
            },
        )

    assert response.status_code == 200
    assert captured["query"] == LIN_A
    rows = response.json()["results"]
    assert len(rows) == 1
    assert rows[0]["orcid"] == LIN_A
    assert rows[0]["source"] == "orcid"
    assert rows[0]["display_name"] == "Lin Lin"
    assert rows[0]["primary_institution"]["name"] == "University of California Berkeley"


def test_orcid_row_hydrates_openalex_by_exact_orcid(monkeypatch):
    async def fake_orcid(**_kwargs):
        return {
            "query": LIN_A,
            "source": "orcid",
            "results": [
                _orcid_candidate(
                    LIN_A,
                    display_name="Lin Lin",
                    institution="University of California Berkeley",
                )
            ],
            "num_found": 1,
            "has_more": False,
        }

    async def fake_oa_by_orcid(orcid, **_kwargs):
        assert orcid == LIN_A
        return {
            "query": LIN_A,
            "entity_type": "authors",
            "source": "openalex",
            "results": [
                {
                    "result_id": "openalex:A501",
                    "result_type": "author",
                    "openalex_id": "A501",
                    "display_name": "Lin Lin",
                    "source": "openalex",
                    "orcid": LIN_A,
                    "works_count": 200,
                    "cited_by_count": 12,
                }
            ],
            "next_cursor": None,
            "has_more": False,
        }

    monkeypatch.setattr(
        "app.integrations.openalex.unified_search.search_openalex_authors_by_orcid",
        fake_oa_by_orcid,
    )

    with patch(
        "app.services.search.orcid_provider.search_orcid_authors",
        side_effect=fake_orcid,
    ):
        response = client.get(
            "/api/search",
            params={"query": LIN_A, "entity_type": "authors", "source": "orcid"},
        )

    assert response.status_code == 200
    row = response.json()["results"][0]
    assert row["source"] == "orcid"
    assert row["orcid"] == LIN_A
    assert row["openalex_id"] == "A501"
    assert row["works_count"] == 200


def test_all_sources_orcid_id_enriches_matching_openalex():
    async def fake_orcid(**kwargs):
        assert kwargs["query"] == LIN_A
        return {
            "query": LIN_A,
            "source": "orcid",
            "results": [
                _orcid_candidate(
                    LIN_A,
                    display_name="Lin Lin",
                    institution="University of California Berkeley",
                )
            ],
            "num_found": 1,
            "has_more": False,
        }

    with (
        patch(
            "app.services.search.orcid_provider.search_orcid_authors",
            side_effect=fake_orcid,
        ),
        patch(
            "app.services.search.openalex_provider.unified_openalex_search",
            new_callable=AsyncMock,
            return_value={
                "query": LIN_A,
                "entity_type": "authors",
                "source": "openalex",
                "results": [
                    {
                        "result_id": "openalex:A501",
                        "result_type": "author",
                        "openalex_id": "A501",
                        "display_name": "Lin Lin",
                        "source": "openalex",
                        "orcid": LIN_A,
                        "works_count": 90,
                    }
                ],
                "next_cursor": None,
                "has_more": False,
            },
        ),
    ):
        response = client.get(
            "/api/search",
            params={"query": LIN_A, "entity_type": "authors", "source": "all"},
        )

    assert response.status_code == 200
    rows = response.json()["results"]
    assert len(rows) == 1
    assert rows[0]["source"] == "orcid"
    assert rows[0]["orcid"] == LIN_A
    assert rows[0]["openalex_id"] == "A501"
    assert rows[0]["works_count"] == 90
    assert rows[0]["primary_institution"]["name"] == "University of California Berkeley"


def test_openalex_without_orcid_stays_separate_from_same_name_orcid_profiles():
    async def fake_orcid(**_kwargs):
        return {
            "query": "Lin Lin",
            "source": "orcid",
            "results": [
                _orcid_candidate(
                    LIN_A,
                    display_name="Lin Lin",
                    institution="University of California Berkeley",
                ),
                _orcid_candidate(
                    LIN_B,
                    display_name="Lin Lin",
                    institution="Shanghai Normal University",
                ),
            ],
            "num_found": 2,
            "has_more": False,
        }

    openalex_row = {
        "result_id": "openalex:A0",
        "result_type": "author",
        "openalex_id": "A0",
        "display_name": "Lin Lin",
        "source": "openalex",
        "orcid": None,
        "works_count": 3,
    }

    with (
        patch(
            "app.services.search.orcid_provider.search_orcid_authors",
            side_effect=fake_orcid,
        ),
        patch(
            "app.services.search.openalex_provider.unified_openalex_search",
            new_callable=AsyncMock,
            return_value={
                "query": "Lin Lin",
                "entity_type": "authors",
                "source": "openalex",
                "results": [openalex_row],
                "next_cursor": None,
                "has_more": False,
            },
        ),
    ):
        response = client.get(
            "/api/search",
            params={"query": "Lin Lin", "entity_type": "authors", "source": "openalex"},
        )

    assert response.status_code == 200
    rows = response.json()["results"]
    assert [row["source"] for row in rows] == ["openalex", "orcid", "orcid"]
    assert {row["orcid"] for row in rows if row["source"] == "orcid"} == {LIN_A, LIN_B}
    assert rows[0]["openalex_id"] == "A0"
    assert rows[0].get("orcid") in (None, "")


def test_all_sources_name_search_keeps_same_name_orcid_profiles_separate():
    async def fake_orcid(**_kwargs):
        return {
            "query": "Lin Lin",
            "source": "orcid",
            "results": [
                _orcid_candidate(
                    LIN_A,
                    display_name="Lin Lin",
                    institution="University of California Berkeley",
                ),
                _orcid_candidate(
                    LIN_B,
                    display_name="Lin Lin",
                    institution="Shanghai Normal University",
                ),
            ],
            "num_found": 2,
            "has_more": False,
        }

    with (
        patch(
            "app.services.search.orcid_provider.search_orcid_authors",
            side_effect=fake_orcid,
        ),
        patch(
            "app.services.search.openalex_provider.unified_openalex_search",
            new_callable=AsyncMock,
            return_value={
                "query": "Lin Lin",
                "entity_type": "authors",
                "source": "openalex",
                "results": [
                    {
                        "result_id": "openalex:A0",
                        "result_type": "author",
                        "openalex_id": "A0",
                        "display_name": "Lin Lin",
                        "source": "openalex",
                        "orcid": None,
                    }
                ],
                "next_cursor": None,
                "has_more": False,
            },
        ),
        patch(
            "app.services.search.arxiv_provider.search_arxiv_authors",
            new_callable=AsyncMock,
            return_value={
                "query": "Lin Lin",
                "entity_type": "authors",
                "source": "arxiv",
                "results": [],
                "next_cursor": None,
                "has_more": False,
            },
        ),
    ):
        response = client.get(
            "/api/search",
            params={"query": "Lin Lin", "entity_type": "authors", "source": "all"},
        )

    assert response.status_code == 200
    rows = response.json()["results"]
    assert [row["source"] for row in rows] == ["openalex", "orcid", "orcid"]
    assert {row["orcid"] for row in rows if row["source"] == "orcid"} == {LIN_A, LIN_B}


def test_orcid_identifier_is_not_treated_as_grant_number():
    from app.integrations.openalex.grant_number import looks_like_grant_number

    assert looks_like_grant_number(LIN_A) is False
    assert looks_like_grant_number(f"https://orcid.org/{LIN_A}") is False
    assert looks_like_grant_number("R01GM123456") is True


def test_name_search_skips_openalex_orcid_hydration(monkeypatch):
    hydrate_called = False

    async def fake_hydrate(results):
        nonlocal hydrate_called
        hydrate_called = True
        return results

    monkeypatch.setattr(
        "app.services.search.search_service._hydrate_orcid_rows_from_openalex",
        fake_hydrate,
    )

    enrich_flags: list[bool | None] = []

    async def fake_orcid(**kwargs):
        enrich_flags.append(kwargs.get("enrich"))
        return {
            "query": kwargs.get("query"),
            "source": "orcid",
            "results": [
                _orcid_candidate(
                    LIN_A,
                    display_name="Lin Lin",
                    institution="University of California Berkeley",
                )
            ],
            "num_found": 1,
            "has_more": False,
        }

    with (
        patch(
            "app.services.search.orcid_provider.search_orcid_authors",
            side_effect=fake_orcid,
        ),
        patch(
            "app.services.search.openalex_provider.unified_openalex_search",
            new_callable=AsyncMock,
            return_value={
                "query": "Lin Lin",
                "entity_type": "authors",
                "source": "openalex",
                "results": [],
                "next_cursor": None,
                "has_more": False,
            },
        ),
    ):
        response = client.get(
            "/api/search",
            params={"query": "Lin Lin", "entity_type": "authors", "source": "openalex"},
        )

    assert response.status_code == 200
    assert enrich_flags == [False]
    assert hydrate_called is False


def test_direct_orcid_search_still_hydrates_openalex(monkeypatch):
    hydrate_called = False

    async def fake_hydrate(results):
        nonlocal hydrate_called
        hydrate_called = True
        return results

    monkeypatch.setattr(
        "app.services.search.search_service._hydrate_orcid_rows_from_openalex",
        fake_hydrate,
    )

    enrich_flags: list[bool | None] = []

    async def fake_orcid(**kwargs):
        enrich_flags.append(kwargs.get("enrich"))
        return {
            "query": LIN_A,
            "source": "orcid",
            "results": [
                _orcid_candidate(
                    LIN_A,
                    display_name="Lin Lin",
                    institution="University of California Berkeley",
                )
            ],
            "num_found": 1,
            "has_more": False,
        }

    with patch(
        "app.services.search.orcid_provider.search_orcid_authors",
        side_effect=fake_orcid,
    ):
        response = client.get(
            "/api/search",
            params={"query": LIN_A, "entity_type": "authors", "source": "orcid"},
        )

    assert response.status_code == 200
    assert enrich_flags == [True]
    assert hydrate_called is True

