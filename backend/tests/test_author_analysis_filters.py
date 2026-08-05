"""Tests for author analysis search persistence and subset filtering."""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.core.config import get_settings
from app.db.models.author_analysis import AuthorAnalysisSearch
from app.db.session import SessionLocal, init_db
from app.integrations.arxiv.client import reset_arxiv_client_state_for_tests
from app.main import app
from app.services.analysis.search_persistence import (
    build_combination_key,
    upsert_author_analysis_search,
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


@pytest.mark.asyncio
async def test_combination_key_is_sorted_active_ids():
    assert build_combination_key(["c2", "c1"]) == "c1,c2"


@pytest.mark.asyncio
async def test_upsert_persists_distinct_combinations(monkeypatch, tmp_path):
    db_path = tmp_path / "analysis_test.db"
    monkeypatch.setenv("DATABASE_URL", f"sqlite+aiosqlite:///{db_path}")
    get_settings.cache_clear()
    await init_db()

    async with SessionLocal() as session:
        await upsert_author_analysis_search(
            session,
            original_author_ids=["c1", "c2", "c3"],
            active_authors=[
                _author(
                    canonical_author_id="c1",
                    provider="openalex",
                    provider_author_id="A1",
                    display_name="John Smith",
                ),
                _author(
                    canonical_author_id="c2",
                    provider="openalex",
                    provider_author_id="A2",
                    display_name="Jane Doe",
                ),
            ],
            mode="common_publications",
            result_count=5,
        )

        row = (
            await session.execute(
                select(AuthorAnalysisSearch).where(
                    AuthorAnalysisSearch.combination_key == "c1,c2"
                )
            )
        ).scalar_one()
        assert row.mode == "common_publications"
        assert row.result_count == 5
        assert row.original_author_ids == ["c1", "c2", "c3"]
        assert row.active_author_names == ["John Smith", "Jane Doe"]

        await upsert_author_analysis_search(
            session,
            original_author_ids=["c1", "c2", "c3"],
            active_authors=[
                _author(
                    canonical_author_id="c1",
                    provider="openalex",
                    provider_author_id="A1",
                    display_name="John Smith",
                )
            ],
            mode="single_author",
            result_count=12,
        )

        common_row = (
            await session.execute(
                select(AuthorAnalysisSearch).where(
                    AuthorAnalysisSearch.combination_key == "c1,c2"
                )
            )
        ).scalar_one()
        single_row = (
            await session.execute(
                select(AuthorAnalysisSearch).where(
                    AuthorAnalysisSearch.combination_key == "c1"
                )
            )
        ).scalar_one()
        assert common_row.mode == "common_publications"
        assert single_row.mode == "single_author"
        assert single_row.result_count == 12


def test_subset_request_returns_single_author_mode(monkeypatch):
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
                    "title": "Solo Paper",
                    "authors": [{"id": "A1", "name": "John Smith"}],
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
                    _author(
                        canonical_author_id="c1",
                        provider="openalex",
                        provider_author_id="A1111111111",
                        display_name="John Smith",
                    )
                ],
                "original_author_ids": ["c1", "c2"],
                "limit": 20,
            },
        )

    assert response.status_code == 200
    body = response.json()
    assert body["mode"] == "single_author"
    assert len(body["items"]) == 1
    assert mock_oa.await_args.kwargs["author_id_groups"] == [["A1111111111"]]


def test_endpoint_persists_successful_first_page(monkeypatch):
    author_id = "c-persist-1"

    with patch(
        "app.services.analysis.author_publications.search_works_by_author_ids",
        new_callable=AsyncMock,
    ) as mock_oa, patch(
        "app.api.routes.analysis.upsert_author_analysis_search",
        new_callable=AsyncMock,
    ) as mock_upsert:
        mock_oa.return_value = {
            "results": [
                {
                    "result_id": "openalex:W1",
                    "result_type": "work",
                    "openalex_id": "W1",
                    "title": "Paper",
                    "authors": [],
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
                    _author(
                        canonical_author_id=author_id,
                        provider="openalex",
                        provider_author_id="A1234567890",
                        display_name="John Smith",
                    )
                ],
                "original_author_ids": ["orig-1", "orig-2"],
                "limit": 20,
            },
        )

    assert response.status_code == 200
    mock_upsert.assert_awaited_once()
    kwargs = mock_upsert.await_args.kwargs
    assert kwargs["original_author_ids"] == ["orig-1", "orig-2"]
    assert kwargs["mode"] == "single_author"
    assert kwargs["result_count"] == 1
    assert kwargs["active_authors"][0]["canonical_author_id"] == author_id


def test_pagination_request_does_not_persist(monkeypatch, tmp_path):
    db_path = tmp_path / "route_no_persist.db"
    monkeypatch.setenv("DATABASE_URL", f"sqlite+aiosqlite:///{db_path}")
    get_settings.cache_clear()

    with patch(
        "app.services.analysis.author_publications.search_works_by_author_ids",
        new_callable=AsyncMock,
    ) as mock_oa, patch(
        "app.api.routes.analysis.upsert_author_analysis_search",
        new_callable=AsyncMock,
    ) as mock_upsert:
        mock_oa.return_value = {
            "results": [],
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
                        provider_author_id="A1234567890",
                        display_name="John Smith",
                    )
                ],
                "cursor": "some-cursor",
                "limit": 20,
            },
        )

    assert response.status_code == 200
    mock_upsert.assert_not_awaited()
