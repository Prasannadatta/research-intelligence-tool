"""Tests for grant suggestions and exact grant publications."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient

from app.core.config import get_settings
from app.integrations.arxiv.client import reset_arxiv_client_state_for_tests
from app.main import app
from app.services.grants.suggestions import suggest_grant_numbers
from app.services.work_persistence.normalization import normalize_grant_number

client = TestClient(app)


@pytest.fixture(autouse=True)
def _reset_settings(monkeypatch):
    monkeypatch.setenv("WORK_PERSISTENCE_ENABLED", "false")
    monkeypatch.setenv("AUTHOR_RESOLUTION_ENABLED", "false")
    monkeypatch.setenv("PROVIDER_SEARCH_CACHE_ENABLED", "false")
    monkeypatch.setenv("OPENALEX_API_KEY", "test-key")
    monkeypatch.setenv("ARXIV_ENABLED", "true")
    reset_arxiv_client_state_for_tests()
    get_settings.cache_clear()
    yield
    reset_arxiv_client_state_for_tests()
    get_settings.cache_clear()


def test_suggestions_require_provider_and_query():
    response = client.get("/api/grants/suggestions", params={"q": "R01"})
    assert response.status_code == 422

    response = client.get(
        "/api/grants/suggestions",
        params={"q": "R", "provider": "openalex"},
    )
    assert response.status_code == 422


def test_suggestions_are_provider_specific_and_separate_similar_numbers():
    with patch(
        "app.services.grants.suggestions.resolve_awards_for_grant_number",
        new_callable=AsyncMock,
    ) as mock_awards:
        mock_awards.return_value = [
            {
                "funder_award_id": "R01GM121772",
                "funder": {"display_name": "National Institutes of Health"},
                "funded_outputs_count": 4,
            },
            {
                "funder_award_id": "R01GM127778",
                "funder": {"display_name": "National Institutes of Health"},
                "funded_outputs_count": 2,
            },
            {
                "funder_award_id": "R01GM123456",
                "funder": {"display_name": "National Institutes of Health"},
                "funded_outputs_count": 1,
            },
        ]

        response = client.get(
            "/api/grants/suggestions",
            params={"q": "R01GM12", "provider": "openalex", "limit": 10},
        )

    assert response.status_code == 200
    body = response.json()
    assert "items" in body
    numbers = [item["grant_number"] for item in body["items"]]
    assert numbers == ["R01GM121772", "R01GM123456", "R01GM127778"] or set(numbers) == {
        "R01GM121772",
        "R01GM127778",
        "R01GM123456",
    }
    assert all(item["provider"] == "openalex" for item in body["items"])
    assert all(item["verified"] is True for item in body["items"])
    # Similar numbers remain separate rows.
    assert len(body["items"]) == 3
    assert len({item["normalized_grant_number"] for item in body["items"]}) == 3


def test_suggestions_do_not_call_other_provider():
    with patch(
        "app.services.grants.suggestions.resolve_awards_for_grant_number",
        new_callable=AsyncMock,
    ) as mock_oa:
        mock_oa.side_effect = AssertionError("OpenAlex must not be called for arxiv")
        response = client.get(
            "/api/grants/suggestions",
            params={"q": "R01GM12", "provider": "arxiv", "limit": 10},
        )

    assert response.status_code == 200
    assert response.json()["items"] == []


def test_empty_suggestions_are_not_errors():
    with patch(
        "app.services.grants.suggestions.resolve_awards_for_grant_number",
        new_callable=AsyncMock,
    ) as mock_awards:
        mock_awards.return_value = []
        response = client.get(
            "/api/grants/suggestions",
            params={"q": "ZZZZ9999", "provider": "openalex"},
        )

    assert response.status_code == 200
    assert response.json()["items"] == []


def test_publications_use_only_selected_provider_openalex():
    with patch(
        "app.services.grants.publications.search_publications_for_grant_number",
        new_callable=AsyncMock,
    ) as mock_oa, patch(
        "app.services.grants.publications.search_arxiv_grants",
        new_callable=AsyncMock,
    ) as mock_arxiv:
        mock_arxiv.side_effect = AssertionError("arXiv must not be called")
        mock_oa.return_value = {
            "results": [
                {
                    "result_id": "openalex:W1",
                    "result_type": "work",
                    "openalex_id": "W1",
                    "title": "Funded Paper",
                    "authors": [{"id": "A1", "name": "Ada"}],
                    "publication_year": 2024,
                    "source": "openalex",
                    "grants": [],
                }
            ],
            "next_cursor": None,
            "has_more": False,
        }

        response = client.get(
            "/api/grants/R01GM127778/publications",
            params={"provider": "openalex", "limit": 20},
        )

    assert response.status_code == 200
    body = response.json()
    assert body["grant_number"] == "R01GM127778"
    assert body["provider"] == "openalex"
    assert body["verified"] is True
    assert body["match_type"] == "structured_award_relationship"
    assert body["pagination"]["has_more"] is False
    assert body["timeline"] is not None
    assert "facets" in body
    assert len(body["items"]) == 1
    assert body["items"][0]["title"] == "Funded Paper"
    assert body["items"][0]["grants"][0]["award_id"] == "R01GM127778"
    assert body["items"][0]["grants"][0]["verified"] is True
    mock_oa.assert_awaited()
    assert mock_oa.await_args.kwargs["query"] == "R01GM127778"


def test_publications_use_only_selected_provider_arxiv():
    with patch(
        "app.services.grants.publications.search_publications_for_grant_number",
        new_callable=AsyncMock,
    ) as mock_oa, patch(
        "app.services.grants.publications.search_arxiv_grants",
        new_callable=AsyncMock,
    ) as mock_arxiv:
        mock_oa.side_effect = AssertionError("OpenAlex must not be called")
        mock_arxiv.return_value = {
            "results": [
                {
                    "result_id": "arxiv:2401.1",
                    "result_type": "work",
                    "source": "arxiv",
                    "source_id": "2401.1",
                    "title": "Preprint Mentions Grant",
                    "authors": [{"id": None, "name": "Ada"}],
                    "publication_year": 2024,
                    "entry_url": "https://arxiv.org/abs/2401.1",
                    "grants": [],
                }
            ],
            "next_cursor": None,
            "has_more": False,
        }

        response = client.get(
            "/api/grants/R01GM127778/publications",
            params={"provider": "arxiv", "limit": 20},
        )

    assert response.status_code == 200
    body = response.json()
    assert body["provider"] == "arxiv"
    assert body["verified"] is False
    assert body["match_type"] == "metadata_text_match"
    assert body["items"][0]["grants"][0]["verified"] is False
    assert body["items"][0]["grants"][0]["match_type"] == "metadata_text_match"
    mock_arxiv.assert_awaited_once()


def test_publications_exact_grant_not_prefix_broadened():
    with patch(
        "app.services.grants.publications.search_publications_for_grant_number",
        new_callable=AsyncMock,
    ) as mock_oa:
        mock_oa.return_value = {
            "results": [],
            "next_cursor": None,
            "has_more": False,
        }
        response = client.get(
            "/api/grants/R01GM127778/publications",
            params={"provider": "openalex"},
        )

    assert response.status_code == 200
    assert response.json()["items"] == []
    assert mock_oa.await_args.kwargs["query"] == "R01GM127778"


def test_publications_filters_affect_timeline_and_table():
    import json

    with patch(
        "app.services.grants.publications.search_publications_for_grant_number",
        new_callable=AsyncMock,
    ) as mock_oa:
        mock_oa.return_value = {
            "results": [
                {
                    "result_id": "openalex:W1",
                    "result_type": "work",
                    "openalex_id": "W1",
                    "title": "Old Paper",
                    "authors": [{"id": "A1", "name": "Ada"}],
                    "publication_year": 2018,
                    "journal": "Nature Medicine",
                    "source": "openalex",
                    "providers": ["openalex"],
                    "grants": [],
                },
                {
                    "result_id": "openalex:W2",
                    "result_type": "work",
                    "openalex_id": "W2",
                    "title": "New Paper",
                    "authors": [{"id": "A2", "name": "Grace"}],
                    "publication_year": 2022,
                    "journal": "Science",
                    "source": "openalex",
                    "providers": ["openalex"],
                    "grants": [],
                },
            ],
            "next_cursor": None,
            "has_more": False,
        }
        response = client.get(
            "/api/grants/R01GM127778/publications",
            params={
                "provider": "openalex",
                "filters": json.dumps({"from_year": 2020, "to_year": 2025}),
            },
        )

    assert response.status_code == 200
    body = response.json()
    assert [item["title"] for item in body["items"]] == ["New Paper"]
    assert body["timeline"]["total_matching_publications"] == 1
    assert body["facets"]["venues"]
    assert body["facets"]["authors"]


def test_publications_return_all_grants_and_mark_searched():
    with patch(
        "app.services.grants.publications.search_publications_for_grant_number",
        new_callable=AsyncMock,
    ) as mock_oa:
        mock_oa.return_value = {
            "results": [
                {
                    "result_id": "openalex:W1",
                    "result_type": "work",
                    "openalex_id": "W1",
                    "title": "Multi Grant Paper",
                    "authors": [{"id": "A1", "name": "Ada"}],
                    "publication_year": 2024,
                    "source": "openalex",
                    "grants": [
                        {
                            "award_id": "R01CA123456",
                            "funder_name": "National Cancer Institute",
                        },
                        {
                            "award_id": "P30CA045508",
                            "funder_name": "National Cancer Institute",
                        },
                        {
                            "award_id": "r01-ca-123456",
                            "funder_name": "National Cancer Institute",
                        },
                        {
                            "award_id": "U01CA987654",
                            "funder_name": "National Cancer Institute",
                        },
                    ],
                }
            ],
            "next_cursor": None,
            "has_more": False,
        }
        response = client.get(
            "/api/grants/R01CA123456/publications",
            params={"provider": "openalex"},
        )

    assert response.status_code == 200
    body = response.json()
    assert len(body["items"]) == 1
    grants = body["items"][0]["grants"]
    numbers = [row["grant_number"] for row in grants]
    assert "R01CA123456" in numbers or any(
        row["normalized_grant_number"] == "r01ca123456" for row in grants
    )
    assert "P30CA045508" in numbers
    assert "U01CA987654" in numbers
    # Duplicate formatting variants collapse to one entry.
    assert sum(1 for row in grants if row["normalized_grant_number"] == "r01ca123456") == 1
    searched = [row for row in grants if row["is_searched_grant"]]
    assert len(searched) == 1
    assert searched[0]["normalized_grant_number"] == "r01ca123456"
    assert searched[0]["funder"] == "National Cancer Institute"


def test_publications_pagination_appends_without_error():
    with patch(
        "app.services.grants.publications.search_publications_for_grant_number",
        new_callable=AsyncMock,
    ) as mock_oa:
        mock_oa.side_effect = [
            {
                "results": [
                    {
                        "result_id": "openalex:W1",
                        "result_type": "work",
                        "openalex_id": "W1",
                        "title": "Page One",
                        "authors": [],
                        "publication_year": 2020,
                        "source": "openalex",
                        "grants": [],
                    },
                    {
                        "result_id": "openalex:W2",
                        "result_type": "work",
                        "openalex_id": "W2",
                        "title": "Page Two",
                        "authors": [],
                        "publication_year": 2021,
                        "source": "openalex",
                        "grants": [],
                    },
                ],
                "next_cursor": None,
                "has_more": False,
            },
            {
                "results": [
                    {
                        "result_id": "openalex:W1",
                        "result_type": "work",
                        "openalex_id": "W1",
                        "title": "Page One",
                        "authors": [],
                        "publication_year": 2020,
                        "source": "openalex",
                        "grants": [],
                    },
                    {
                        "result_id": "openalex:W2",
                        "result_type": "work",
                        "openalex_id": "W2",
                        "title": "Page Two",
                        "authors": [],
                        "publication_year": 2021,
                        "source": "openalex",
                        "grants": [],
                    },
                ],
                "next_cursor": None,
                "has_more": False,
            },
        ]
        first = client.get(
            "/api/grants/R01GM127778/publications",
            params={"provider": "openalex", "limit": 1},
        )
        assert first.status_code == 200
        body = first.json()
        assert len(body["items"]) == 1
        assert body["pagination"]["has_more"] is True
        assert body["timeline"] is not None
        cursor = body["pagination"]["next_cursor"]
        assert cursor

        second = client.get(
            "/api/grants/R01GM127778/publications",
            params={"provider": "openalex", "cursor": cursor, "limit": 1},
        )

    assert second.status_code == 200
    assert len(second.json()["items"]) == 1
    assert second.json()["items"][0]["title"] == "Page Two"
    assert second.json()["timeline"] is None


def test_encoded_grant_number_is_decoded():
    with patch(
        "app.services.grants.publications.search_publications_for_grant_number",
        new_callable=AsyncMock,
    ) as mock_oa:
        mock_oa.return_value = {
            "results": [],
            "next_cursor": None,
            "has_more": False,
        }
        response = client.get(
            "/api/grants/R01%20GM127778/publications",
            params={"provider": "openalex"},
        )

    assert response.status_code == 200
    assert mock_oa.await_args.kwargs["query"] == "R01 GM127778"


def test_normalize_keeps_similar_grants_distinct():
    a = normalize_grant_number("R01GM121772")
    b = normalize_grant_number("R01GM127778")
    assert a != b


@pytest.mark.asyncio
async def test_db_suggestions_prefer_prefix_rank_without_provider_call():
    class _Row:
        def __init__(self, **kwargs):
            self.__dict__.update(kwargs)

    class _Result:
        def __init__(self, rows):
            self._rows = rows

        def all(self):
            return self._rows

    class _Session:
        def __init__(self):
            self.calls = 0

        async def execute(self, _stmt):
            self.calls += 1
            if self.calls == 1:
                return _Result(
                    [
                        _Row(
                            normalized_grant_number="r01gm127778",
                            provider="openalex",
                            grant_number="R01GM127778",
                            verified=True,
                            publication_count=4,
                        ),
                        _Row(
                            normalized_grant_number="r01gm121772",
                            provider="openalex",
                            grant_number="R01GM121772",
                            verified=True,
                            publication_count=2,
                        ),
                    ]
                )
            return _Result([])

    with patch(
        "app.services.grants.suggestions.resolve_awards_for_grant_number",
        new_callable=AsyncMock,
    ) as mock_oa:
        mock_oa.side_effect = AssertionError("should use DB rows")
        payload = await suggest_grant_numbers(
            _Session(),
            q="R01GM12",
            provider="openalex",
            limit=10,
        )

    assert len(payload["items"]) == 2
    assert {item["grant_number"] for item in payload["items"]} == {
        "R01GM127778",
        "R01GM121772",
    }
