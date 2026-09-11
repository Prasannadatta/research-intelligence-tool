"""Tests for the ORCID public API client and provider-author normalization."""

from __future__ import annotations

import httpx
import pytest

from app.core.config import get_settings
from app.integrations.orcid.client import (
    OrcidApiError,
    OrcidClient,
    reset_orcid_client_state_for_tests,
    search_orcid_authors,
)
from app.integrations.orcid.normalize import (
    build_orcid_author_query,
    candidate_from_orcid_payloads,
    normalize_orcid_id,
    parse_employments_payload,
    parse_works_payload,
)

LIN_LIN_BERKELEY = "0000-0001-6860-9566"
LIN_LIN_EDUCATION = "0000-0002-2400-5864"

EXPANDED_LIN_LIN = {
    "num-found": 655,
    "expanded-result": [
        {
            "orcid-id": LIN_LIN_BERKELEY,
            "given-names": "Lin",
            "family-names": "Lin",
            "credit-name": None,
            "other-name": [],
            "institution-name": [
                "California Institute of Technology",
                "University of California Berkeley",
            ],
        },
        {
            "orcid-id": LIN_LIN_EDUCATION,
            "given-names": "Lin",
            "family-names": "Lin",
            "credit-name": None,
            "other-name": [],
            "institution-name": [
                "Nanjing Normal University",
                "Shanghai Normal University",
                "University of California, Berkeley",
            ],
        },
        {
            "orcid-id": "0000-0001-5052-1216",
            "given-names": "Lin",
            "family-names": "Lin",
            "institution-name": ["中央财经大学"],
        },
    ],
}

PERSON_BERKELEY = {
    "name": {
        "given-names": {"value": "Lin"},
        "family-name": {"value": "Lin"},
        "credit-name": None,
        "visibility": "public",
    },
    "other-names": {"other-name": []},
    "keywords": {"keyword": []},
    "external-identifiers": {"external-identifier": []},
}

PERSON_EDUCATION = {
    "name": {
        "given-names": {"value": "Lin"},
        "family-name": {"value": "Lin"},
    },
    "other-names": {"other-name": []},
    "keywords": {
        "keyword": [{"content": "Design thinking; technology-enhance learning"}],
    },
    "external-identifiers": {
        "external-identifier": [
            {
                "external-id-type": "Scopus Author ID",
                "external-id-value": "57215487997",
                "external-id-url": {
                    "value": "http://www.scopus.com/inward/authorDetails.url?authorID=57215487997&partnerID=MN8TOARS"
                },
            }
        ]
    },
}

EMPLOYMENTS_BERKELEY = {
    "affiliation-group": [
        {
            "summaries": [
                {
                    "employment-summary": {
                        "department-name": "Mathematics",
                        "role-title": "Professor",
                        "start-date": None,
                        "end-date": None,
                        "organization": {
                            "name": "University of California Berkeley",
                            "address": {"city": "Berkeley", "region": "CA", "country": "US"},
                            "disambiguated-organization": {
                                "disambiguated-organization-identifier": "1438",
                                "disambiguation-source": "RINGGOLD",
                            },
                        },
                    }
                }
            ]
        },
        {
            "summaries": [
                {
                    "employment-summary": {
                        "department-name": "Computing and Mathematical Sciences",
                        "role-title": "Judge Shirley Hufstedler Professor",
                        "start-date": {"year": {"value": "2026"}, "month": {"value": "07"}, "day": {"value": "01"}},
                        "end-date": None,
                        "organization": {
                            "name": "California Institute of Technology",
                            "address": {
                                "city": "Pasadena",
                                "region": "California",
                                "country": "US",
                            },
                            "disambiguated-organization": {
                                "disambiguated-organization-identifier": "https://ror.org/05dxps055",
                                "disambiguation-source": "ROR",
                            },
                        },
                    }
                }
            ]
        },
    ]
}

EMPLOYMENTS_EDUCATION = {
    "affiliation-group": [
        {
            "summaries": [
                {
                    "employment-summary": {
                        "start-date": {"year": {"value": "2021"}},
                        "end-date": None,
                        "organization": {
                            "name": "Shanghai Normal University",
                            "address": {"city": "Shanghai", "country": "CN"},
                            "disambiguated-organization": {
                                "disambiguated-organization-identifier": "https://ror.org/01cxqmw89",
                                "disambiguation-source": "ROR",
                            },
                        },
                    }
                }
            ]
        }
    ]
}

WORKS_BERKELEY = {
    "group": [
        {
            "external-ids": {
                "external-id": [{"external-id-type": "doi", "external-id-value": "10.1038/s41567-026-03389-y"}]
            },
            "work-summary": [
                {
                    "put-code": 223440859,
                    "title": {"title": {"value": "Simple and efficient end-to-end quantum thermal and ground state preparation"}},
                    "type": "journal-article",
                    "publication-date": {"year": {"value": "2026"}},
                }
            ],
        },
        {
            "external-ids": {
                "external-id": [{"external-id-type": "doi", "external-id-value": "10.1137/25M1806120"}]
            },
            "work-summary": [
                {
                    "put-code": 220513390,
                    "title": {"title": {"value": "Mathematical and Numerical Analysis of Quantum Signal Processing"}},
                    "publication-date": {"year": {"value": "2026"}},
                }
            ],
        },
    ]
}

WORKS_EDUCATION = {
    "group": [
        {
            "external-ids": {
                "external-id": [
                    {"external-id-type": "doi", "external-id-value": "10.1016/j.tsc.2023.101450"},
                    {"external-id-type": "eid", "external-id-value": "2-s2.0-85100000000"},
                ]
            },
            "work-summary": [
                {
                    "title": {
                        "title": {
                            "value": "Exploring the Impact of Design Thinking in Information Technology Education"
                        }
                    },
                    "publication-date": {"year": {"value": "2023"}},
                }
            ],
        }
    ]
}


@pytest.fixture(autouse=True)
def _orcid_settings(monkeypatch):
    monkeypatch.setenv("ORCID_ENABLED", "true")
    monkeypatch.setenv("ORCID_PUBLIC_BASE_URL", "https://pub.orcid.org/v3.0")
    monkeypatch.setenv(
        "ORCID_USER_AGENT",
        "ResearchIntelligencePlatform/0.1 mailto:research-intelligence@berkeley.edu",
    )
    reset_orcid_client_state_for_tests()
    get_settings.cache_clear()
    yield
    reset_orcid_client_state_for_tests()
    get_settings.cache_clear()


def _json_response(payload: dict, status_code: int = 200) -> httpx.Response:
    return httpx.Response(status_code, json=payload)


class _FakeOrcidHttp:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str, dict | None]] = []

    async def __call__(self, provider, url, *, params=None, headers=None, timeout=None, **kwargs):
        assert provider == "orcid"
        assert headers["Accept"] == "application/json"
        assert "User-Agent" in headers
        self.calls.append((url, str(params), headers))
        path = url.split("https://pub.orcid.org/v3.0", 1)[-1]
        if path.startswith("/expanded-search"):
            return _json_response(EXPANDED_LIN_LIN)
        if path == f"/{LIN_LIN_BERKELEY}/person":
            return _json_response(PERSON_BERKELEY)
        if path == f"/{LIN_LIN_EDUCATION}/person":
            return _json_response(PERSON_EDUCATION)
        if path == f"/{LIN_LIN_BERKELEY}/employments":
            return _json_response(EMPLOYMENTS_BERKELEY)
        if path == f"/{LIN_LIN_EDUCATION}/employments":
            return _json_response(EMPLOYMENTS_EDUCATION)
        if path == f"/{LIN_LIN_BERKELEY}/works":
            return _json_response(WORKS_BERKELEY)
        if path == f"/{LIN_LIN_EDUCATION}/works":
            return _json_response(WORKS_EDUCATION)
        if path.endswith("/person"):
            return _json_response(PERSON_BERKELEY)
        if path.endswith("/employments"):
            return _json_response({"affiliation-group": []})
        if path.endswith("/works"):
            return _json_response({"group": []})
        return httpx.Response(404, json={"error": "not found"})


def test_normalize_orcid_id_from_url_and_bare():
    assert normalize_orcid_id("https://orcid.org/0000-0001-6860-9566") == LIN_LIN_BERKELEY
    assert normalize_orcid_id("0000-0001-6860-9566/") == LIN_LIN_BERKELEY
    assert normalize_orcid_id("0000-0002-1825-009x") == "0000-0002-1825-009X"
    assert normalize_orcid_id("not-an-orcid") is None
    assert normalize_orcid_id("") is None


def test_structured_search_query_for_lin_lin_and_head_gordon():
    assert (
        build_orcid_author_query("Lin Lin")
        == 'given-names:"Lin" AND family-name:"Lin"'
    )
    assert (
        build_orcid_author_query("Martin Head-Gordon")
        == 'given-names:"Martin" AND family-name:"Head-Gordon"'
    )
    assert (
        build_orcid_author_query("Lin Lin", affiliation="Berkeley")
        == 'given-names:"Lin" AND family-name:"Lin" AND affiliation-org-name:"Berkeley"'
    )
    assert build_orcid_author_query(LIN_LIN_BERKELEY) == f"orcid:{LIN_LIN_BERKELEY}"
    assert build_orcid_author_query('given-names:"Lin" AND family-name:"Lin"').startswith(
        "given-names:"
    )


def test_candidate_normalization_keeps_orcid_as_provider_id():
    candidate = candidate_from_orcid_payloads(
        orcid=f"https://orcid.org/{LIN_LIN_BERKELEY}",
        search_hit=EXPANDED_LIN_LIN["expanded-result"][0],
        person=PERSON_BERKELEY,
        employments_payload=EMPLOYMENTS_BERKELEY,
        works_payload=WORKS_BERKELEY,
    )
    assert candidate is not None
    assert candidate.provider == "orcid"
    assert candidate.provider_author_id == LIN_LIN_BERKELEY
    assert candidate.orcid == LIN_LIN_BERKELEY
    assert candidate.display_name == "Lin Lin"
    assert candidate.raw_metadata["given_names"] == "Lin"
    assert candidate.raw_metadata["family_name"] == "Lin"
    names = {inst.name for inst in candidate.institutions}
    assert "University of California Berkeley" in names
    assert "California Institute of Technology" in names
    caltech = next(emp for emp in candidate.raw_metadata["employments"] if "Caltech" in (emp["name"] or "") or "California Institute of Technology" in (emp["name"] or ""))
    assert caltech["start_date"] == "2026-07-01"
    assert caltech["end_date"] is None
    assert candidate.works_count == 2
    assert [work.id for work in candidate.works] == [
        "10.1038/s41567-026-03389-y",
        "10.1137/25M1806120",
    ]
    assert all(work.id_type == "doi" for work in candidate.works)


def test_external_ids_and_employment_dates_on_education_lin_lin():
    candidate = candidate_from_orcid_payloads(
        orcid=LIN_LIN_EDUCATION,
        search_hit=EXPANDED_LIN_LIN["expanded-result"][1],
        person=PERSON_EDUCATION,
        employments_payload=EMPLOYMENTS_EDUCATION,
        works_payload=WORKS_EDUCATION,
    )
    assert candidate is not None
    assert candidate.provider_author_id == LIN_LIN_EDUCATION
    assert candidate.raw_metadata["external_ids"] == [
        {
            "type": "Scopus Author ID",
            "value": "57215487997",
            "url": "http://www.scopus.com/inward/authorDetails.url?authorID=57215487997&partnerID=MN8TOARS",
        }
    ]
    assert candidate.raw_metadata["employments"][0]["start_date"] == "2021"
    assert candidate.works[0].id == "10.1016/j.tsc.2023.101450"


def test_parse_works_counts_groups_and_extracts_dois():
    parsed = parse_works_payload(WORKS_BERKELEY)
    assert parsed["works_count"] == 2
    assert parsed["dois"] == [
        "10.1038/s41567-026-03389-y",
        "10.1137/25M1806120",
    ]
    employments = parse_employments_payload(EMPLOYMENTS_BERKELEY)
    assert len(employments) == 2
    assert employments[0]["role"] == "Professor"


@pytest.mark.asyncio
async def test_lin_lin_search_keeps_ambiguous_orcid_records_separate():
    fake = _FakeOrcidHttp()
    client = OrcidClient(request_func=fake)
    payload = await search_orcid_authors(query="Lin Lin", enrich=True, client=client)
    assert payload["source"] == "orcid"
    assert payload["query"] == 'given-names:"Lin" AND family-name:"Lin"'
    assert payload["num_found"] == 655
    ids = [row.provider_author_id for row in payload["results"]]
    assert ids == [LIN_LIN_BERKELEY, LIN_LIN_EDUCATION, "0000-0001-5052-1216"]
    assert len(set(ids)) == 3
    berkeley = payload["results"][0]
    education = payload["results"][1]
    assert berkeley.orcid != education.orcid
    assert berkeley.display_name == education.display_name == "Lin Lin"
    assert any("Berkeley" in (inst.name or "") for inst in berkeley.institutions)
    assert education.raw_metadata["external_ids"][0]["value"] == "57215487997"
    assert berkeley.works_count == 2
    search_urls = [url for url, _, _ in fake.calls if "expanded-search" in url]
    assert search_urls
    assert fake.calls[0][2]["Accept"] == "application/json"


@pytest.mark.asyncio
async def test_name_search_without_enrich_uses_expanded_search_only():
    fake = _FakeOrcidHttp()
    client = OrcidClient(request_func=fake)
    payload = await search_orcid_authors(query="Lin Lin", enrich=False, client=client)
    assert [row.orcid for row in payload["results"]] == [
        LIN_LIN_BERKELEY,
        LIN_LIN_EDUCATION,
        "0000-0001-5052-1216",
    ]
    assert any("Berkeley" in (inst.name or "") for inst in payload["results"][0].institutions)
    urls = [url for url, _, _ in fake.calls]
    assert any("expanded-search" in url for url in urls)
    assert not any(url.endswith("/person") for url in urls)
    assert not any(url.endswith("/employments") for url in urls)
    assert not any(url.endswith("/works") for url in urls)


@pytest.mark.asyncio
async def test_assembled_search_payload_is_cached():
    fake = _FakeOrcidHttp()
    client = OrcidClient(request_func=fake)
    first = await search_orcid_authors(query="Lin Lin", enrich=False, client=client)
    second = await search_orcid_authors(query="Lin Lin", enrich=False, client=client)
    assert [row.orcid for row in first["results"]] == [row.orcid for row in second["results"]]
    search_calls = [url for url, _, _ in fake.calls if "expanded-search" in url]
    assert len(search_calls) == 1


@pytest.mark.asyncio
async def test_affiliation_narrows_query_without_merging_names():
    captured = {}

    async def capture(provider, url, *, params=None, headers=None, timeout=None, **kwargs):
        captured["params"] = params
        return _json_response({"num-found": 2, "expanded-result": EXPANDED_LIN_LIN["expanded-result"][:2]})

    client = OrcidClient(request_func=capture)
    payload = await search_orcid_authors(
        query="Lin Lin",
        affiliation="Berkeley",
        enrich=False,
        client=client,
    )
    assert captured["params"]["q"] == (
        'given-names:"Lin" AND family-name:"Lin" AND affiliation-org-name:"Berkeley"'
    )
    assert [row.orcid for row in payload["results"]] == [LIN_LIN_BERKELEY, LIN_LIN_EDUCATION]


@pytest.mark.asyncio
async def test_orcid_api_failure_returns_empty_results():
    async def boom(provider, url, *, params=None, headers=None, timeout=None, **kwargs):
        return httpx.Response(500, json={"error": "unavailable"})

    payload = await search_orcid_authors(
        query="Lin Lin",
        client=OrcidClient(request_func=boom),
    )
    assert payload["results"] == []
    assert payload["num_found"] == 0
    assert payload["source"] == "orcid"


@pytest.mark.asyncio
async def test_disabled_orcid_returns_empty_without_http(monkeypatch):
    monkeypatch.setenv("ORCID_ENABLED", "false")
    get_settings.cache_clear()

    async def should_not_run(*args, **kwargs):
        raise AssertionError("ORCID HTTP should not run when disabled")

    payload = await search_orcid_authors(
        query="Lin Lin",
        client=OrcidClient(request_func=should_not_run),
    )
    assert payload["results"] == []


@pytest.mark.asyncio
async def test_client_endpoints_and_invalid_orcid():
    fake = _FakeOrcidHttp()
    client = OrcidClient(request_func=fake)
    person = await client.get_person(LIN_LIN_BERKELEY)
    assert person["name"]["given-names"]["value"] == "Lin"
    works = await client.get_works(LIN_LIN_BERKELEY)
    assert len(works["group"]) == 2
    employments = await client.get_employments(LIN_LIN_BERKELEY)
    assert employments["affiliation-group"]
    with pytest.raises(OrcidApiError) as exc:
        await client.get_person("not-valid")
    assert exc.value.status_code == 422


@pytest.mark.asyncio
async def test_client_uses_cache_for_repeated_person_reads():
    fake = _FakeOrcidHttp()
    client = OrcidClient(request_func=fake)
    await client.get_person(LIN_LIN_BERKELEY)
    await client.get_person(LIN_LIN_BERKELEY)
    person_calls = [url for url, _, _ in fake.calls if url.endswith("/person")]
    assert len(person_calls) == 1


@pytest.mark.asyncio
async def test_orcid_id_query_fetches_person_not_expanded_search():
    fake = _FakeOrcidHttp()
    client = OrcidClient(request_func=fake)
    payload = await search_orcid_authors(query=LIN_LIN_BERKELEY, enrich=False, client=client)
    assert payload["num_found"] == 1
    assert payload["results"][0].orcid == LIN_LIN_BERKELEY
    assert payload["results"][0].display_name == "Lin Lin"
    urls = [url for url, _, _ in fake.calls]
    assert any(url.endswith(f"/{LIN_LIN_BERKELEY}/person") for url in urls)
    assert not any("expanded-search" in url for url in urls)
    assert not any(url.endswith("/employments") for url in urls)
    assert not any(url.endswith("/works") for url in urls)


@pytest.mark.asyncio
async def test_orcid_id_lookup_fetches_person_once_when_enriched():
    fake = _FakeOrcidHttp()
    client = OrcidClient(request_func=fake)
    await search_orcid_authors(query=LIN_LIN_BERKELEY, enrich=True, client=client)
    person_calls = [url for url, _, _ in fake.calls if url.endswith("/person")]
    assert len(person_calls) == 1


@pytest.mark.asyncio
async def test_unknown_orcid_id_returns_empty_without_name_search():
    async def missing(provider, url, *, params=None, headers=None, timeout=None, **kwargs):
        assert "expanded-search" not in url
        return httpx.Response(404, json={"error": "not found"})

    payload = await search_orcid_authors(
        query=LIN_LIN_BERKELEY,
        client=OrcidClient(request_func=missing),
    )
    assert payload["results"] == []
    assert payload["num_found"] == 0

