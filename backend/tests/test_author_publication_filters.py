"""Unit and API tests for author publication filters and facets."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient

from app.core.config import get_settings
from app.integrations.arxiv.client import reset_arxiv_client_state_for_tests
from app.main import app
from app.services.analysis.publication_filters import (
    apply_publication_filters,
    build_publication_facets,
    item_matches_filters,
    normalize_grant_number,
    normalize_venue_key,
)

client = TestClient(app)


@pytest.fixture(autouse=True)
def _reset_settings(monkeypatch):
    monkeypatch.setenv("WORK_PERSISTENCE_ENABLED", "false")
    monkeypatch.setenv("AUTHOR_RESOLUTION_ENABLED", "false")
    monkeypatch.setenv("PROVIDER_SEARCH_CACHE_ENABLED", "false")
    monkeypatch.setenv("OPENALEX_API_KEY", "test-key")
    monkeypatch.setenv("ARXIV_ENABLED", "false")
    reset_arxiv_client_state_for_tests()
    get_settings.cache_clear()
    yield
    reset_arxiv_client_state_for_tests()
    get_settings.cache_clear()


def _author():
    return {
        "canonical_author_id": "author-1",
        "provider": "openalex",
        "provider_author_id": "A1234567890",
        "display_name": "Jane Doe",
    }


def _sample_items():
    return [
        {
            "id": "1",
            "publication_year": 2021,
            "providers": ["openalex", "arxiv"],
            "journal": "Nature Medicine",
            "grants": [
                {
                    "award_id": "R01-CA-123456",
                    "funder_name": "National Cancer Institute",
                    "verified": True,
                }
            ],
            "analysis_match": {"verified": True, "method": "provider_author_ids"},
            "title": "Paper A",
        },
        {
            "id": "2",
            "publication_year": 2019,
            "providers": ["openalex"],
            "journal": "nature medicine",
            "grants": [
                {
                    "award_id": "R01CA123456",
                    "funder_name": "NCI",
                    "verified": True,
                }
            ],
            "analysis_match": {"verified": True, "method": "provider_author_ids"},
            "title": "Paper B",
        },
        {
            "id": "3",
            "publication_year": 2022,
            "providers": ["arxiv"],
            "primary_source": "bioRxiv",
            "grants": [],
            "analysis_match": {"verified": False, "method": "metadata_author_name_match"},
            "title": "Paper C",
        },
        {
            "id": "4",
            "publication_year": 2023,
            "providers": ["openalex"],
            "journal": "Science",
            "grants": [
                {
                    "award_id": "U01HG000001",
                    "funder_name": "NHGRI",
                    "verified": True,
                }
            ],
            "analysis_match": {"verified": True, "method": "provider_author_ids"},
            "title": "Paper D",
        },
    ]


def test_normalize_venue_and_grant_keys():
    assert normalize_venue_key(" Nature Medicine ") == "nature medicine"
    assert normalize_grant_number("R01-CA 123456") == "r01ca123456"


def test_year_range_filter():
    items = _sample_items()
    filtered = apply_publication_filters(items, {"from_year": 2020, "to_year": 2022})
    assert [row["id"] for row in filtered] == ["1", "3"]


def test_multi_source_or_and_cross_category_and():
    items = _sample_items()
    # OR within sources
    by_source = apply_publication_filters(items, {"sources": ["arxiv"]})
    assert {row["id"] for row in by_source} == {"1", "3"}

    # AND across categories: openalex AND Nature Medicine
    crossed = apply_publication_filters(
        items,
        {"sources": ["openalex"], "venues": ["Nature Medicine"]},
    )
    assert {row["id"] for row in crossed} == {"1", "2"}


def test_venue_and_grant_facets_dedupe_with_counts():
    facets = build_publication_facets(_sample_items())
    venues = {row["value"]: row for row in facets["venues"]}
    assert venues["nature medicine"]["count"] == 2
    assert venues["nature medicine"]["label"] == "Nature Medicine"

    grants = {normalize_grant_number(row["grant_number"]): row for row in facets["grants"]}
    assert grants["r01ca123456"]["publication_count"] == 2


def test_multi_venue_or_and_grant_or():
    items = _sample_items()
    venues = apply_publication_filters(
        items,
        {"venues": ["Nature Medicine", "bioRxiv"]},
    )
    assert {row["id"] for row in venues} == {"1", "2", "3"}

    grants = apply_publication_filters(
        items,
        {"grant_numbers": ["R01CA123456", "U01HG000001"]},
    )
    assert {row["id"] for row in grants} == {"1", "2", "4"}


def test_canonical_work_matches_any_selected_source():
    item = _sample_items()[0]
    assert item_matches_filters(item, {"sources": ["arxiv"]})
    assert item_matches_filters(item, {"sources": ["openalex"]})
    assert not item_matches_filters(item, {"sources": ["pubmed"]})


def test_analysis_endpoint_applies_filters_and_returns_facets(monkeypatch):
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
                    "title": "Paper One",
                    "authors": [{"id": "A1", "name": "Jane Doe"}],
                    "publication_year": 2021,
                    "primary_source": "Nature Medicine",
                    "cited_by_count": 10,
                    "source": "openalex",
                    "grants": [
                        {
                            "award_id": "R01CA123456",
                            "funder_name": "National Cancer Institute",
                            "verified": True,
                            "match_type": "structured_award_relationship",
                            "provider": "openalex",
                        }
                    ],
                },
                {
                    "result_id": "openalex:W2",
                    "result_type": "work",
                    "openalex_id": "W2",
                    "title": "Paper Two",
                    "authors": [{"id": "A1", "name": "Jane Doe"}],
                    "publication_year": 2018,
                    "primary_source": "Science",
                    "cited_by_count": 3,
                    "source": "openalex",
                    "grants": [],
                },
            ],
            "next_cursor": None,
            "has_more": False,
        }

        response = client.post(
            "/api/analysis/authors/publications",
            json={
                "authors": [_author()],
                "limit": 20,
                "cursor": None,
                "filters": {
                    "from_year": 2020,
                    "to_year": 2026,
                    "sources": ["openalex"],
                    "venues": ["Nature Medicine"],
                    "grant_numbers": ["R01CA123456"],
                },
            },
        )

    assert response.status_code == 200
    payload = response.json()
    assert len(payload["items"]) == 1
    assert payload["items"][0]["title"] == "Paper One"
    assert payload["timeline"]["total_matching_publications"] == 1
    assert any(row["value"] == "openalex" for row in payload["facets"]["sources"])
    assert any(row["value"] == "nature medicine" for row in payload["facets"]["venues"])
    assert any(
        row["grant_number"] == "R01CA123456" for row in payload["facets"]["grants"]
    )


def test_pagination_preserves_filters(monkeypatch):
    results = [
        {
            "result_id": f"openalex:W{i}",
            "result_type": "work",
            "openalex_id": f"W{i}",
            "title": f"Paper {i}",
            "authors": [{"id": "A1", "name": "Jane Doe"}],
            "publication_year": 2021,
            "primary_source": "Nature Medicine",
            "cited_by_count": i,
            "source": "openalex",
            "grants": [],
        }
        for i in range(1, 25)
    ]

    with patch(
        "app.services.analysis.author_publications.search_works_by_author_ids",
        new_callable=AsyncMock,
    ) as mock_oa:
        mock_oa.return_value = {
            "results": results,
            "next_cursor": None,
            "has_more": False,
        }

        first = client.post(
            "/api/analysis/authors/publications",
            json={
                "authors": [_author()],
                "limit": 20,
                "filters": {"venues": ["Nature Medicine"]},
            },
        )
        assert first.status_code == 200
        first_payload = first.json()
        assert len(first_payload["items"]) == 20
        assert first_payload["pagination"]["has_more"] is True
        cursor = first_payload["pagination"]["next_cursor"]
        assert cursor

        second = client.post(
            "/api/analysis/authors/publications",
            json={
                "authors": [_author()],
                "limit": 20,
                "cursor": cursor,
                "filters": {"venues": ["Nature Medicine"]},
            },
        )
        assert second.status_code == 200
        second_payload = second.json()
        assert len(second_payload["items"]) == 4
        assert second_payload["timeline"] is None
