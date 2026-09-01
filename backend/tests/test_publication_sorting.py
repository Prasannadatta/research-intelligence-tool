"""Tests for global publication sorting before pagination."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient

from app.core.config import get_settings
from app.integrations.arxiv.client import reset_arxiv_client_state_for_tests
from app.main import app

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


def _author_payload() -> dict:
    return {
        "canonical_author_id": "author-1",
        "provider": "openalex",
        "provider_author_id": "A1234567890",
        "display_name": "Ada Lovelace",
    }


def _work(
    work_id: str,
    title: str,
    *,
    year: int | None,
    citations: int | None,
    venue: str | None,
    author_count: int,
) -> dict:
    authors = [{"id": f"A{index}", "name": f"Author {index}"} for index in range(author_count)]
    return {
        "result_id": f"openalex:{work_id}",
        "result_type": "work",
        "openalex_id": work_id,
        "title": title,
        "authors": authors,
        "publication_year": year,
        "primary_source": venue,
        "citation_count": citations,
        "cited_by_count": citations,
        "source": "openalex",
        "grants": [],
    }


def test_author_publications_sort_year_before_pagination(monkeypatch):
    with patch(
        "app.services.analysis.author_publications.search_works_by_author_ids",
        new_callable=AsyncMock,
    ) as mock_oa:
        mock_oa.return_value = {
            "results": [
                _work("W1", "Older", year=2020, citations=3, venue="B", author_count=1),
                _work("W2", "Newest", year=2024, citations=1, venue="A", author_count=1),
                _work("W3", "Missing Year", year=None, citations=10, venue="C", author_count=1),
            ],
            "next_cursor": None,
            "has_more": False,
        }

        response = client.post(
            "/api/analysis/authors/publications",
            json={
                "authors": [_author_payload()],
                "sort_by": "year",
                "sort_direction": "desc",
                "limit": 1,
            },
        )

    assert response.status_code == 200
    body = response.json()
    assert [item["title"] for item in body["items"]] == ["Newest"]
    assert body["pagination"]["has_more"] is True


def test_author_publications_sort_missing_values_after_known_values(monkeypatch):
    with patch(
        "app.services.analysis.author_publications.search_works_by_author_ids",
        new_callable=AsyncMock,
    ) as mock_oa:
        mock_oa.return_value = {
            "results": [
                _work("W1", "Missing Citations", year=2021, citations=None, venue="B", author_count=1),
                _work("W2", "Real Zero", year=2021, citations=0, venue="A", author_count=1),
                _work("W3", "Highly Cited", year=2021, citations=12, venue="C", author_count=1),
            ],
            "next_cursor": None,
            "has_more": False,
        }

        response = client.post(
            "/api/analysis/authors/publications",
            json={
                "authors": [_author_payload()],
                "sort_by": "citations",
                "sort_direction": "desc",
                "limit": 3,
            },
        )

    assert response.status_code == 200
    assert [item["title"] for item in response.json()["items"]] == [
        "Highly Cited",
        "Real Zero",
        "Missing Citations",
    ]


def test_author_publications_sort_title_venue_and_author_count(monkeypatch):
    works = [
        _work("W1", "beta", year=2021, citations=1, venue="Zoo", author_count=1),
        _work("W2", "Alpha", year=2021, citations=1, venue="middle", author_count=4),
        _work("W3", "gamma", year=2021, citations=1, venue="Archive", author_count=2),
    ]

    for sort_by, expected in [
        ("title", ["Alpha", "beta", "gamma"]),
        ("venue", ["gamma", "Alpha", "beta"]),
        ("author_count", ["beta", "gamma", "Alpha"]),
    ]:
        with patch(
            "app.services.analysis.author_publications.search_works_by_author_ids",
            new_callable=AsyncMock,
        ) as mock_oa:
            mock_oa.return_value = {
                "results": works,
                "next_cursor": None,
                "has_more": False,
            }

            response = client.post(
                "/api/analysis/authors/publications",
                json={
                    "authors": [_author_payload()],
                    "sort_by": sort_by,
                    "sort_direction": "asc",
                    "limit": 3,
                },
            )

        assert response.status_code == 200
        assert [item["title"] for item in response.json()["items"]] == expected


def test_grant_publications_sorting_is_before_pagination(monkeypatch):
    with patch(
        "app.services.grants.publications.search_publications_for_grant_number",
        new_callable=AsyncMock,
    ) as mock_oa:
        mock_oa.return_value = {
            "results": [
                _work("GW1", "Low", year=2021, citations=1, venue="B", author_count=1),
                _work("GW2", "High", year=2020, citations=50, venue="A", author_count=3),
            ],
            "next_cursor": None,
            "has_more": False,
        }

        response = client.get(
            "/api/grants/R01GM123456/publications",
            params={
                "provider": "openalex",
                "sort_by": "citations",
                "sort_direction": "desc",
                "limit": 1,
            },
        )

    assert response.status_code == 200
    body = response.json()
    assert [item["title"] for item in body["items"]] == ["High"]
    assert body["pagination"]["has_more"] is True
