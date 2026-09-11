"""Author-search institution/topic filters: OpenAlex filter construction + wiring."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import httpx
import pytest
from fastapi.testclient import TestClient

from app.core.config import get_settings
from app.main import app
from app.services.search.openalex_provider import clear_author_page_cache

client = TestClient(app)

UCB = "I95457486"
TOPIC_ML = "T11948"


@pytest.fixture(autouse=True)
def _settings(monkeypatch):
    monkeypatch.setenv("AUTHOR_RESOLUTION_ENABLED", "false")
    monkeypatch.setenv("WORK_PERSISTENCE_ENABLED", "false")
    monkeypatch.setenv("PROVIDER_SEARCH_CACHE_ENABLED", "false")
    monkeypatch.setenv("ORCID_ENABLED", "true")
    clear_author_page_cache()
    get_settings.cache_clear()
    yield
    clear_author_page_cache()
    get_settings.cache_clear()


def _json_response(payload: dict, status_code: int = 200) -> httpx.Response:
    return httpx.Response(status_code, json=payload, request=httpx.Request("GET", "https://api.openalex.org/"))


@pytest.mark.asyncio
async def test_author_search_builds_last_known_institution_and_topic_filters():
    captured: dict = {}

    async def fake_get(url, *, params=None, **_kwargs):
        captured["url"] = url
        captured["params"] = dict(params or {})
        return _json_response(
            {
                "results": [],
                "meta": {"next_cursor": None, "count": 0},
            }
        )

    with (
        patch(
            "app.integrations.openalex.unified_search._require_api_key",
            return_value="test-key",
        ),
        patch(
            "app.integrations.openalex.unified_search._openalex_get",
            side_effect=fake_get,
        ),
    ):
        from app.integrations.openalex.unified_search import unified_openalex_search

        await unified_openalex_search(
            query="Lin Lin",
            entity_type="authors",
            limit=5,
            institution_id=UCB,
            topic_id=TOPIC_ML,
        )

    assert captured["params"]["search"] == "Lin Lin"
    assert (
        captured["params"]["filter"]
        == f"last_known_institutions.id:{UCB},topics.id:{TOPIC_ML}"
    )
    assert "affiliations.institution.id" not in captured["params"]["filter"]


@pytest.mark.asyncio
async def test_institution_only_filter_uses_last_known_institutions():
    captured: dict = {}

    async def fake_get(url, *, params=None, **_kwargs):
        captured["params"] = dict(params or {})
        return _json_response({"results": [], "meta": {}})

    with (
        patch(
            "app.integrations.openalex.unified_search._require_api_key",
            return_value="test-key",
        ),
        patch(
            "app.integrations.openalex.unified_search._openalex_get",
            side_effect=fake_get,
        ),
    ):
        from app.integrations.openalex.unified_search import unified_openalex_search

        await unified_openalex_search(
            query="Lin Lin",
            entity_type="authors",
            institution_id=f"https://openalex.org/{UCB}",
        )

    assert captured["params"]["filter"] == f"last_known_institutions.id:{UCB}"


def test_invalid_institution_id_rejected():
    response = client.get(
        "/api/search",
        params={
            "query": "Lin Lin",
            "entity_type": "authors",
            "source": "openalex",
            "institution_id": "not-an-id",
        },
    )
    assert response.status_code == 422


def test_filter_autocomplete_endpoints_normalize_options():
    async def fake_institutions(query, limit=10):
        assert query == "Berkeley"
        return [
            {
                "id": UCB,
                "display_name": "University of California, Berkeley",
                "country_code": "US",
                "type": "education",
                "works_count": 1,
                "source": "openalex",
            }
        ]

    async def fake_topics(query, limit=10):
        assert query == "machine learning"
        return [
            {
                "id": TOPIC_ML,
                "display_name": "Machine Learning in Materials Science",
                "description": "desc",
                "works_count": 2,
                "source": "openalex",
            }
        ]

    with (
        patch(
            "app.api.routes.search.search_institutions",
            side_effect=fake_institutions,
        ),
        patch(
            "app.api.routes.search.search_topics",
            side_effect=fake_topics,
        ),
    ):
        institutions = client.get(
            "/api/search/filters/institutions",
            params={"query": "Berkeley"},
        )
        topics = client.get(
            "/api/search/filters/topics",
            params={"query": "machine learning"},
        )

    assert institutions.status_code == 200
    assert institutions.json()[0]["id"] == UCB
    assert topics.status_code == 200
    assert topics.json()[0]["id"] == TOPIC_ML


def test_openalex_search_forwards_institution_and_topic_ids():
    captured = {}

    async def fake_oa(**kwargs):
        captured.update(kwargs)
        return {
            "query": "Lin Lin",
            "entity_type": "authors",
            "source": "openalex",
            "results": [],
            "next_cursor": None,
            "has_more": False,
        }

    with patch(
        "app.services.search.openalex_provider.unified_openalex_search",
        side_effect=fake_oa,
    ):
        response = client.get(
            "/api/search",
            params={
                "query": "Lin Lin",
                "entity_type": "authors",
                "source": "openalex",
                "institution_id": UCB,
                "topic_id": TOPIC_ML,
            },
        )

    assert response.status_code == 200
    assert captured["institution_id"] == UCB
    assert captured["topic_id"] == TOPIC_ML


def test_normalize_prefers_filtered_institution_as_primary():
    from app.integrations.openalex.unified_search import normalize_search_author

    author = {
        "id": "https://openalex.org/A1",
        "display_name": "Lin Lin",
        "affiliations": [
            {
                "is_current": True,
                "institution": {
                    "id": "https://openalex.org/I111",
                    "display_name": "Other University",
                    "country_code": "CN",
                    "type": "education",
                },
            }
        ],
        "last_known_institutions": [
            {
                "id": f"https://openalex.org/{UCB}",
                "display_name": "University of California, Berkeley",
                "country_code": "US",
                "type": "education",
            }
        ],
        "topics": [],
    }
    row = normalize_search_author(author, prefer_institution_id=UCB)
    assert row is not None
    assert row["primary_institution"]["id"] == UCB
    assert row["primary_institution"]["name"] == "University of California, Berkeley"


def test_all_with_filters_skips_orcid_and_drops_orcid_only_rows():
    orcid_called = False

    async def fake_orcid(**_kwargs):
        nonlocal orcid_called
        orcid_called = True
        return {
            "query": "Lin Lin",
            "source": "orcid",
            "results": [],
            "num_found": 0,
            "has_more": False,
        }

    async def fake_oa(**kwargs):
        assert kwargs.get("institution_id") == UCB
        return {
            "query": "Lin Lin",
            "entity_type": "authors",
            "source": "openalex",
            "results": [
                {
                    "result_id": "openalex:A1",
                    "result_type": "author",
                    "openalex_id": "A1",
                    "display_name": "Lin Lin",
                    "source": "openalex",
                    "orcid": "0000-0001-6860-9566",
                    "primary_institution": {
                        "id": UCB,
                        "name": "University of California, Berkeley",
                    },
                }
            ],
            "next_cursor": None,
            "has_more": False,
        }

    with (
        patch(
            "app.services.search.orcid_provider.search_orcid_authors",
            side_effect=fake_orcid,
        ),
        patch(
            "app.services.search.openalex_provider.unified_openalex_search",
            side_effect=fake_oa,
        ),
    ):
        response = client.get(
            "/api/search",
            params={
                "query": "Lin Lin",
                "entity_type": "authors",
                "source": "all",
                "institution_id": UCB,
            },
        )

    assert response.status_code == 200
    assert orcid_called is False
    rows = response.json()["results"]
    assert all(row["source"] == "openalex" for row in rows)
    assert all(row.get("openalex_id") for row in rows)
