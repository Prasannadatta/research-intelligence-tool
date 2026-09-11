"""Tests for author publication analysis endpoint."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient

from app.core.config import get_settings
from app.integrations.arxiv.client import reset_arxiv_client_state_for_tests
from app.main import app
from app.services.analysis.author_publications import (
    METHOD_METADATA_NAMES,
    METHOD_PROVIDER_IDS,
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


def _author(
    *,
    canonical_author_id: str,
    provider: str,
    provider_author_id: str,
    display_name: str,
) -> dict:
    return {
        "canonical_author_id": canonical_author_id,
        "provider": provider,
        "provider_author_id": provider_author_id,
        "display_name": display_name,
    }


def test_single_author_openalex_publications(monkeypatch):
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
                    "title": "Paper One",
                    "authors": [{"id": "A1", "name": "John Smith"}],
                    "publication_year": 2024,
                    "primary_source": "Nature",
                    "cited_by_count": 10,
                    "doi": "10.1000/test",
                    "source": "openalex",
                    "grants": [
                        {
                            "award_id": "R01GM123456",
                            "funder_name": "National Institutes of Health",
                            "verified": True,
                            "match_type": "structured_award_relationship",
                            "provider": "openalex",
                        }
                    ],
                }
            ],
            "next_cursor": None,
            "has_more": False,
            "count": 1,
        }

        response = client.post(
            "/api/analysis/authors/publications",
            json={
                "authors": [
                    _author(
                        canonical_author_id="author-1",
                        provider="openalex",
                        provider_author_id="A1234567890",
                        display_name="John Smith",
                    )
                ],
                "limit": 20,
                "cursor": None,
            },
        )

    assert response.status_code == 200
    body = response.json()
    assert body["mode"] == "single_author"
    assert body["unsupported"] is False
    assert body["pagination"]["has_more"] is False
    assert len(body["items"]) == 1
    item = body["items"][0]
    assert item["title"] == "Paper One"
    assert item["analysis_match"]["verified"] is True
    assert item["analysis_match"]["method"] == METHOD_PROVIDER_IDS
    assert item["grants"][0]["award_id"] == "R01GM123456"
    assert mock_oa.await_count == 1
    # Timeline/facets come from the corpus stats job, not live table pages.
    assert body["timeline"] is None
    assert body["facets"] == {
        "sources": [],
        "institutions": [],
        "venues": [],
        "grants": [],
        "authors": [],
    }
    assert mock_oa.await_args.kwargs["author_id_groups"] == [["A1234567890"]]
    assert body["provider_total_count"] == 1


def test_multi_author_uses_openalex_intersection_filter(monkeypatch):
    monkeypatch.setenv("ARXIV_ENABLED", "false")
    get_settings.cache_clear()

    with patch(
        "app.services.analysis.author_publications.search_works_by_author_ids",
        new_callable=AsyncMock,
    ) as mock_oa:
        async def openalex_side_effect(*_args, cursor=None, **_kwargs):
            page = {
                "results": [
                    {
                        "result_id": "openalex:W2",
                        "result_type": "work",
                        "openalex_id": "W2",
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
            }
            if cursor in (None, "", "*"):
                return {
                    **page,
                    "next_cursor": "next-token",
                    "has_more": True,
                }
            return {**page, "next_cursor": None, "has_more": False}

        mock_oa.side_effect = openalex_side_effect

        response = client.post(
            "/api/analysis/authors/publications",
            json={
                "authors": [
                    _author(
                        canonical_author_id="c1",
                        provider="openalex",
                        provider_author_id="A1111111111",
                        display_name="John Smith",
                    ),
                    _author(
                        canonical_author_id="c2",
                        provider="openalex",
                        provider_author_id="A2222222222",
                        display_name="Jane Doe",
                    ),
                ],
                "limit": 20,
            },
        )

    assert response.status_code == 200
    body = response.json()
    assert body["mode"] == "common_publications"
    assert body["pagination"]["has_more"] is True
    assert body["pagination"]["next_cursor"]
    assert len(body["items"]) == 1
    assert body["items"][0]["analysis_match"]["verified"] is True
    assert mock_oa.await_count == 1
    assert mock_oa.await_args.kwargs["author_id_groups"] == [
        ["A1111111111"],
        ["A2222222222"],
    ]


def test_three_author_openalex_intersection_fetches_one_page(monkeypatch):
    monkeypatch.setenv("ARXIV_ENABLED", "true")
    get_settings.cache_clear()

    with patch(
        "app.services.analysis.author_publications.search_works_by_author_ids",
        new_callable=AsyncMock,
    ) as mock_oa, patch(
        "app.services.analysis.author_publications.search_arxiv_publications_by_authors",
        new_callable=AsyncMock,
    ) as mock_arxiv:
        mock_arxiv.side_effect = AssertionError("arXiv should not be queried")
        mock_oa.return_value = {
            "results": [
                {
                    "result_id": "openalex:W3",
                    "result_type": "work",
                    "openalex_id": "W3",
                    "title": "Triple Paper",
                    "authors": [
                        {"id": "A1", "name": "John Smith"},
                        {"id": "A2", "name": "Jane Doe"},
                        {"id": "A3", "name": "Alex Roe"},
                    ],
                    "publication_year": 2022,
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
                    _author(
                        canonical_author_id="c1",
                        provider="openalex",
                        provider_author_id="A1111111111",
                        display_name="John Smith",
                    ),
                    _author(
                        canonical_author_id="c2",
                        provider="openalex",
                        provider_author_id="A2222222222",
                        display_name="Jane Doe",
                    ),
                    _author(
                        canonical_author_id="c3",
                        provider="openalex",
                        provider_author_id="A3333333333",
                        display_name="Alex Roe",
                    ),
                ],
                "limit": 20,
            },
        )

    assert response.status_code == 200
    body = response.json()
    assert body["mode"] == "common_publications"
    assert len(body["items"]) == 1
    assert body["items"][0]["title"] == "Triple Paper"
    assert mock_oa.await_count == 1
    assert mock_oa.await_args.kwargs["author_id_groups"] == [
        ["A1111111111"],
        ["A2222222222"],
        ["A3333333333"],
    ]
    assert mock_arxiv.await_count == 0
    get_settings.cache_clear()


def test_multi_author_arxiv_marks_experimental():
    with patch(
        "app.services.analysis.author_publications.search_works_by_author_ids",
        new_callable=AsyncMock,
    ) as mock_oa, patch(
        "app.services.analysis.author_publications.search_arxiv_publications_by_authors",
        new_callable=AsyncMock,
    ) as mock_arxiv:
        mock_oa.side_effect = AssertionError("OpenAlex should not be called")
        mock_arxiv.return_value = {
            "results": [
                {
                    "result_id": "arxiv:2401.12345",
                    "result_type": "work",
                    "source": "arxiv",
                    "source_id": "2401.12345",
                    "title": "Joint Preprint",
                    "authors": [
                        {"id": None, "name": "John Smith"},
                        {"id": None, "name": "Jane Doe"},
                    ],
                    "publication_year": 2024,
                    "entry_url": "https://arxiv.org/abs/2401.12345",
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
                    _author(
                        canonical_author_id="arxiv-author-name:john smith",
                        provider="arxiv",
                        provider_author_id="arxiv-author-name:john smith",
                        display_name="John Smith",
                    ),
                    _author(
                        canonical_author_id="arxiv-author-name:jane doe",
                        provider="arxiv",
                        provider_author_id="arxiv-author-name:jane doe",
                        display_name="Jane Doe",
                    ),
                ],
                "limit": 20,
            },
        )

    assert response.status_code == 200
    body = response.json()
    assert body["mode"] == "common_publications"
    assert len(body["items"]) == 1
    assert body["items"][0]["analysis_match"]["verified"] is False
    assert body["items"][0]["analysis_match"]["method"] == METHOD_METADATA_NAMES
    assert mock_arxiv.await_count == 1


@pytest.mark.asyncio
async def test_build_author_id_filter_is_intersection():
    from app.integrations.openalex.author_works import (
        build_author_id_filter,
        build_grouped_author_id_filter,
    )

    assert (
        build_author_id_filter(["A1", "A2"])
        == "author.id:A1,author.id:A2"
    )
    assert (
        build_grouped_author_id_filter([["A1111111111", "A2222222222"], ["A3333333333"]])
        == "author.id:A1111111111|A2222222222,author.id:A3333333333"
    )
    assert build_grouped_author_id_filter([["A9999999999"]]) == "author.id:A9999999999"


def test_empty_authors_rejected():
    response = client.post(
        "/api/analysis/authors/publications",
        json={"authors": [], "limit": 20},
    )
    assert response.status_code == 422


def test_single_author_passes_all_linked_openalex_ids_as_or_group():
    """Canonical authors may have multiple OpenAlex records; combine via OR."""
    with patch(
        "app.services.analysis.author_publications.search_works_by_author_ids",
        new_callable=AsyncMock,
    ) as mock_oa, patch(
        "app.services.analysis.author_publications._resolve_author",
        new_callable=AsyncMock,
    ) as mock_resolve:
        from app.services.analysis.author_publications import ResolvedAuthorContext

        mock_resolve.return_value = ResolvedAuthorContext(
            canonical_author_id="canonical-1",
            display_name="John Smith",
            request_provider="openalex",
            request_provider_author_id="A1111111111",
            openalex_ids=["A1111111111", "A2222222222"],
            arxiv_names=[],
            provider_records_used=[
                {"provider": "openalex", "provider_author_id": "A1111111111"},
                {"provider": "openalex", "provider_author_id": "A2222222222"},
            ],
        )
        mock_oa.return_value = {
            "results": [
                {
                    "result_id": "openalex:W9",
                    "result_type": "work",
                    "openalex_id": "W9",
                    "title": "Merged Identity Paper",
                    "authors": [{"id": "A1", "name": "John Smith"}],
                    "publication_year": 2022,
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
                    _author(
                        canonical_author_id="canonical-1",
                        provider="openalex",
                        provider_author_id="A1111111111",
                        display_name="John Smith",
                    )
                ],
                "limit": 20,
            },
        )

    assert response.status_code == 200
    assert mock_oa.await_args.kwargs["author_id_groups"] == [
        ["A1111111111", "A2222222222"]
    ]
    assert response.json()["items"][0]["analysis_match"]["verified"] is True


def test_openalex_only_author_does_not_query_arxiv_or_follow_cursor(monkeypatch):
    monkeypatch.setenv("ARXIV_ENABLED", "true")
    get_settings.cache_clear()

    with patch(
        "app.services.analysis.author_publications.search_works_by_author_ids",
        new_callable=AsyncMock,
    ) as mock_oa, patch(
        "app.services.analysis.author_publications.search_arxiv_publications_by_authors",
        new_callable=AsyncMock,
    ) as mock_arxiv:
        mock_arxiv.side_effect = AssertionError("arXiv should not be queried")

        async def openalex_pages(*_args, cursor=None, **_kwargs):
            if cursor in (None, "", "*"):
                return {
                    "results": [
                        {
                            "result_id": "openalex:W1",
                            "result_type": "work",
                            "openalex_id": "W1",
                            "title": "First Page Only",
                            "authors": [{"id": "A1", "name": "John Smith"}],
                            "publication_year": 2024,
                            "source": "openalex",
                            "grants": [],
                        }
                    ],
                    "next_cursor": "page-2",
                    "has_more": True,
                    "count": 1037,
                }
            raise AssertionError("OpenAlex next_cursor must not be followed on page 1")

        mock_oa.side_effect = openalex_pages

        response = client.post(
            "/api/analysis/authors/publications",
            json={
                "authors": [
                    _author(
                        canonical_author_id="author-1",
                        provider="openalex",
                        provider_author_id="A1234567890",
                        display_name="John Smith",
                    )
                ],
                "limit": 20,
                "cursor": None,
            },
        )

    assert response.status_code == 200
    body = response.json()
    assert len(body["items"]) == 1
    assert body["items"][0]["title"] == "First Page Only"
    assert body["pagination"]["has_more"] is True
    assert mock_oa.await_count == 1
    assert mock_arxiv.await_count == 0
    assert body["provider_total_count"] == 1037
    get_settings.cache_clear()


def test_arxiv_only_publications_omit_provider_total_count():
    with patch(
        "app.services.analysis.author_publications.search_works_by_author_ids",
        new_callable=AsyncMock,
    ) as mock_oa, patch(
        "app.services.analysis.author_publications.search_arxiv_publications_by_authors",
        new_callable=AsyncMock,
    ) as mock_arxiv:
        mock_oa.side_effect = AssertionError("OpenAlex should not be called")
        mock_arxiv.return_value = {
            "results": [
                {
                    "result_id": "arxiv:2401.12345",
                    "result_type": "work",
                    "source": "arxiv",
                    "source_id": "2401.12345",
                    "title": "Preprint",
                    "authors": [{"id": None, "name": "John Smith"}],
                    "publication_year": 2024,
                    "entry_url": "https://arxiv.org/abs/2401.12345",
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
                    _author(
                        canonical_author_id="arxiv-author-name:john smith",
                        provider="arxiv",
                        provider_author_id="arxiv-author-name:john smith",
                        display_name="John Smith",
                    )
                ],
                "limit": 20,
            },
        )

    assert response.status_code == 200
    assert response.json()["provider_total_count"] is None
    assert mock_arxiv.await_count == 1
