"""Tests for resolve-on-select author identity endpoint."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient

from app.core.config import get_settings
from app.main import app

client = TestClient(app)


@pytest.fixture(autouse=True)
def _settings(monkeypatch):
    monkeypatch.setenv("AUTHOR_RESOLUTION_ENABLED", "true")
    from app.services.search.openalex_provider import clear_author_page_cache

    clear_author_page_cache()
    get_settings.cache_clear()
    yield
    clear_author_page_cache()
    get_settings.cache_clear()


def test_resolve_selected_authors_writes_identity_once():
    provider_row = {
        "result_id": "openalex:A123",
        "result_type": "author",
        "openalex_id": "A123",
        "display_name": "Ada Lovelace",
        "source": "openalex",
        "orcid": None,
        "works_count": 12,
    }
    resolved_row = {
        "id": "11111111-1111-4111-8111-111111111111",
        "result_id": "11111111-1111-4111-8111-111111111111",
        "display_name": "Ada Lovelace",
        "source": "openalex",
        "openalex_id": "A123",
        "source_records": [
            {"provider": "openalex", "provider_author_id": "A123"},
        ],
    }

    with patch(
        "app.api.routes.authors.resolve_selected_authors",
        new_callable=AsyncMock,
        return_value=[resolved_row],
    ) as mocked:
        response = client.post("/api/authors/resolve", json={"authors": [provider_row]})

    assert response.status_code == 200
    assert response.json()["results"][0]["result_id"] == resolved_row["result_id"]
    mocked.assert_awaited_once()


def test_search_does_not_resolve_authors(monkeypatch):
    monkeypatch.setenv("AUTHOR_RESOLUTION_ENABLED", "true")
    get_settings.cache_clear()

    with (
        patch(
            "app.services.authors.resolve.resolve_selected_authors",
            new_callable=AsyncMock,
        ) as resolve_mock,
        patch(
            "app.services.search.openalex_provider.unified_openalex_search",
            new_callable=AsyncMock,
            return_value={
                "query": "Ada",
                "entity_type": "authors",
                "source": "openalex",
                "results": [
                    {
                        "result_id": "openalex:A1",
                        "result_type": "author",
                        "openalex_id": "A1",
                        "display_name": "Ada",
                        "source": "openalex",
                    }
                ],
                "next_cursor": None,
                "has_more": False,
            },
        ),
    ):
        response = client.get(
            "/api/search",
            params={"query": "Ada Lovelace", "entity_type": "authors", "source": "openalex"},
        )

    assert response.status_code == 200
    assert response.json()["results"][0]["openalex_id"] == "A1"
    resolve_mock.assert_not_called()
    assert "items" not in response.json() or not response.json().get("items")
