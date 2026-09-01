"""Tests for publication timeline aggregation."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient

from app.core.config import get_settings
from app.integrations.arxiv.client import reset_arxiv_client_state_for_tests
from app.main import app
from app.services.analysis.author_publications import (
    _encode_cursor,
    build_publication_timeline,
)

client = TestClient(app)


@pytest.fixture(autouse=True)
def _reset_settings(monkeypatch):
    monkeypatch.setenv("WORK_PERSISTENCE_ENABLED", "false")
    monkeypatch.setenv("AUTHOR_RESOLUTION_ENABLED", "false")
    monkeypatch.setenv("PROVIDER_SEARCH_CACHE_ENABLED", "false")
    monkeypatch.setenv("OPENALEX_API_KEY", "test-key")
    reset_arxiv_client_state_for_tests()
    get_settings.cache_clear()
    yield
    reset_arxiv_client_state_for_tests()
    get_settings.cache_clear()


def _work(
    work_id: str,
    *,
    publication_date: str | None = None,
    publication_year: int | None = None,
) -> dict:
    row = {
        "id": work_id,
        "title": f"Paper {work_id}",
        "analysis_match": {"verified": True, "method": "provider_author_ids"},
    }
    if publication_date is not None:
        row["publication_date"] = publication_date
    if publication_year is not None:
        row["publication_year"] = publication_year
    return row


def test_build_timeline_single_author_monthly_grouping():
    items = [
        _work("w1", publication_date="2024-01-15"),
        _work("w2", publication_date="2024-01-20"),
        _work("w3", publication_date="2024-03-01"),
    ]
    timeline = build_publication_timeline(items)
    assert timeline is not None
    assert timeline["interval"] == "month"
    assert [row["period"] for row in timeline["items"]] == [
        "2024-01",
        "2024-02",
        "2024-03",
    ]
    assert timeline["items"][0]["count"] == 2
    assert timeline["items"][1]["count"] == 0
    assert timeline["items"][2]["count"] == 1


def test_build_timeline_year_grouping_for_long_span():
    items = [
        _work("w1", publication_year=2010),
        _work("w2", publication_year=2020),
    ]
    timeline = build_publication_timeline(items)
    assert timeline is not None
    assert timeline["interval"] == "year"
    periods = [row["period"] for row in timeline["items"]]
    assert periods == [str(year) for year in range(2010, 2021)]
    assert timeline["items"][0]["count"] == 1
    assert timeline["items"][10]["count"] == 1
    assert timeline["items"][5]["count"] == 0


def test_build_timeline_ignores_duplicate_canonical_works():
    items = [
        _work("w1", publication_date="2023-06-01"),
        _work("w1", publication_date="2023-06-15"),
        _work("w2", publication_year=2023),
    ]
    timeline = build_publication_timeline(items)
    assert timeline is not None
    assert sum(row["count"] for row in timeline["items"]) == 2


def test_build_timeline_ignores_records_without_dates():
    items = [
        _work("w1"),
        {"id": "w2", "title": "Undated", "analysis_match": {"verified": True, "method": "x"}},
    ]
    assert build_publication_timeline(items) is None


def test_build_timeline_chronological_order():
    items = [
        _work("w1", publication_year=2022),
        _work("w2", publication_year=2020),
        _work("w3", publication_year=2021),
    ]
    timeline = build_publication_timeline(items)
    assert timeline is not None
    assert [row["period"] for row in timeline["items"]] == [
        "2020",
        "2021",
        "2022",
    ]
    assert timeline["total_dated_publications"] == 3
    assert timeline["total_matching_publications"] == 3


def test_build_timeline_mixed_month_and_year_only_uses_yearly():
    items = [
        _work("w1", publication_date="2024-03-01"),
        _work("w2", publication_year=2023),
    ]
    timeline = build_publication_timeline(items)
    assert timeline is not None
    assert timeline["interval"] == "year"
    assert timeline["total_dated_publications"] == 2
    assert timeline["total_matching_publications"] == 2
    assert sum(row["count"] for row in timeline["items"]) == 2


def test_build_timeline_exposes_matching_and_dated_totals():
    items = [
        _work("w1", publication_date="2024-01-15"),
        _work("w2"),
    ]
    timeline = build_publication_timeline(items)
    assert timeline is not None
    assert timeline["total_matching_publications"] == 2
    assert timeline["total_dated_publications"] == 1
    assert sum(row["count"] for row in timeline["items"]) == 1


def test_single_author_endpoint_timeline_uses_fetched_page_only(monkeypatch):
    monkeypatch.setenv("ARXIV_ENABLED", "false")
    get_settings.cache_clear()
    page_one = [
        {
            "result_id": "openalex:W1",
            "result_type": "work",
            "openalex_id": "W1",
            "title": "Page One Paper",
            "authors": [{"id": "A1", "name": "John Smith"}],
            "publication_date": "2024-01-10",
            "source": "openalex",
            "grants": [],
        }
    ]
    page_two = [
        {
            "result_id": "openalex:W2",
            "result_type": "work",
            "openalex_id": "W2",
            "title": "Page Two Paper",
            "authors": [{"id": "A1", "name": "John Smith"}],
            "publication_date": "2024-03-10",
            "source": "openalex",
            "grants": [],
        }
    ]

    with patch(
        "app.services.analysis.author_publications.search_works_by_author_ids",
        new_callable=AsyncMock,
    ) as mock_oa:
        async def openalex_pages(*_args, cursor=None, **_kwargs):
            if cursor in (None, "", "*"):
                return {
                    "results": page_one,
                    "next_cursor": "next",
                    "has_more": True,
                }
            return {
                "results": page_two,
                "next_cursor": None,
                "has_more": False,
            }

        mock_oa.side_effect = openalex_pages

        response = client.post(
            "/api/analysis/authors/publications",
            json={
                "authors": [
                    {
                        "canonical_author_id": "author-1",
                        "provider": "openalex",
                        "provider_author_id": "A1234567890",
                        "display_name": "John Smith",
                    }
                ],
                "limit": 1,
                "cursor": None,
            },
        )

    assert response.status_code == 200
    body = response.json()
    assert body["mode"] == "single_author"
    assert len(body["items"]) == 1
    assert body["timeline"] is not None
    assert body["timeline"]["interval"] == "month"
    assert body["timeline"]["total_dated_publications"] == 1
    assert body["timeline"]["total_matching_publications"] == 1
    assert sum(row["count"] for row in body["timeline"]["items"]) == 1
    assert body["pagination"]["has_more"] is True
    assert mock_oa.await_count == 1


def test_multi_author_timeline_uses_common_publications_only(monkeypatch):
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
                    "title": "Shared Paper",
                    "authors": [
                        {"id": "A1", "name": "John Smith"},
                        {"id": "A2", "name": "Jane Doe"},
                    ],
                    "publication_year": 2023,
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
                        "canonical_author_id": "c1",
                        "provider": "openalex",
                        "provider_author_id": "A1111111111",
                        "display_name": "John Smith",
                    },
                    {
                        "canonical_author_id": "c2",
                        "provider": "openalex",
                        "provider_author_id": "A2222222222",
                        "display_name": "Jane Doe",
                    },
                ],
                "limit": 20,
            },
        )

    assert response.status_code == 200
    body = response.json()
    assert body["mode"] == "common_publications"
    assert body["timeline"]["items"][0]["count"] == 1
    assert mock_oa.await_args.kwargs["author_id_groups"] == [
        ["A1111111111"],
        ["A2222222222"],
    ]


def test_paginated_request_omits_timeline_recalculation(monkeypatch):
    monkeypatch.setenv("ARXIV_ENABLED", "false")
    get_settings.cache_clear()
    cursor_payload = _encode_cursor(
        {
            "v": 2,
            "mode": "single_author",
            "authors_key": "author-1",
            "records_key": "author-1:openalex:A1234567890",
            "filters_key": "from:|to:|sources:|venues:|grants:|authors:",
            "offset": 1,
            "limit": 20,
        }
    )

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
                    "title": "First Page",
                    "authors": [{"id": "A1", "name": "John Smith"}],
                    "publication_year": 2021,
                    "source": "openalex",
                    "grants": [],
                },
                {
                    "result_id": "openalex:W2",
                    "result_type": "work",
                    "openalex_id": "W2",
                    "title": "Second Page",
                    "authors": [{"id": "A1", "name": "John Smith"}],
                    "publication_year": 2022,
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
                "authors": [
                    {
                        "canonical_author_id": "author-1",
                        "provider": "openalex",
                        "provider_author_id": "A1234567890",
                        "display_name": "John Smith",
                    }
                ],
                "limit": 20,
                "cursor": cursor_payload,
            },
        )

    assert response.status_code == 200
    body = response.json()
    assert body["timeline"] is None
    assert len(body["items"]) == 1
    assert body["items"][0]["title"] == "Second Page"
