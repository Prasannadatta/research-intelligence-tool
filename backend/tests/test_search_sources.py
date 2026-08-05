"""Backend tests for search capabilities, OpenAlex routing, and arXiv integration."""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient

from app.core.config import get_settings
from app.integrations.arxiv import client as arxiv_client
from app.integrations.arxiv.client import (
    build_arxiv_cursor,
    reset_arxiv_client_state_for_tests,
    validate_arxiv_cursor,
)
from app.integrations.arxiv.parser import (
    extract_arxiv_id,
    normalize_arxiv_work,
    parse_arxiv_feed,
)
from app.main import app
from app.services.search.providers import get_search_capabilities

client = TestClient(app)

SAMPLE_ATOM = """<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns="http://www.w3.org/2005/Atom"
      xmlns:opensearch="http://a9.com/-/spec/opensearch/1.1/">
  <opensearch:totalResults>42</opensearch:totalResults>
  <entry>
    <id>http://arxiv.org/abs/2401.12345v2</id>
    <title>Quantum Computing Foundations</title>
    <summary>An overview of quantum computing.</summary>
    <published>2024-01-15T00:00:00Z</published>
    <updated>2024-02-01T00:00:00Z</updated>
    <author><name>Alice Example</name></author>
    <author><name>Bob Example</name></author>
    <link href="https://arxiv.org/abs/2401.12345v2" rel="alternate" type="text/html"/>
    <link title="pdf" href="https://arxiv.org/pdf/2401.12345v2" rel="related" type="application/pdf"/>
    <category term="cs.AI"/>
    <category term="cs.LG"/>
  </entry>
</feed>
"""


@pytest.fixture(autouse=True)
def _reset_arxiv_state(monkeypatch):
    # Keep provider-routing tests independent of works persistence / L2 cache.
    monkeypatch.setenv("WORK_PERSISTENCE_ENABLED", "false")
    monkeypatch.setenv("PROVIDER_SEARCH_CACHE_ENABLED", "false")
    reset_arxiv_client_state_for_tests()
    get_settings.cache_clear()
    yield
    reset_arxiv_client_state_for_tests()
    get_settings.cache_clear()


def test_capabilities_include_openalex_arxiv_and_disabled_all():
    response = client.get("/api/search/capabilities")
    assert response.status_code == 200
    payload = response.json()
    assert payload["default_source"] == "openalex"
    by_id = {item["id"]: item for item in payload["sources"]}
    assert by_id["openalex"]["enabled"] is True
    assert set(by_id["openalex"]["supported_entity_types"]) == {
        "authors",
        "works",
        "grants",
    }
    assert by_id["arxiv"]["enabled"] is True
    assert set(by_id["arxiv"]["supported_entity_types"]) == {
        "authors",
        "works",
        "grants",
    }
    assert "authors" in by_id["arxiv"]["experimental_entity_types"]
    assert by_id["all"]["enabled"] is False
    assert by_id["all"]["supported_entity_types"] == []


def test_openalex_authors_works_grants_remain_routable():
    """OpenAlex remains available for Authors, Works, and Grants."""
    with patch(
        "app.services.search.openalex_provider.unified_openalex_search",
        new_callable=AsyncMock,
    ) as mock_search:
        mock_search.return_value = {
            "query": "alice",
            "entity_type": "authors",
            "source": "openalex",
            "results": [],
            "next_cursor": None,
            "has_more": False,
        }
        authors = client.get(
            "/api/search",
            params={"query": "alice", "entity_type": "authors", "source": "openalex"},
        )
        assert authors.status_code == 200
        assert authors.json()["source"] == "openalex"

        mock_search.return_value = {
            "query": "quantum",
            "entity_type": "works",
            "source": "openalex",
            "results": [],
            "next_cursor": None,
            "has_more": False,
        }
        works = client.get(
            "/api/search",
            params={"query": "quantum", "entity_type": "works", "source": "openalex"},
        )
        assert works.status_code == 200

        mock_search.return_value = {
            "query": "R01GM123456",
            "entity_type": "grants",
            "source": "openalex",
            "results": [
                {
                    "result_id": "openalex:W1",
                    "result_type": "work",
                    "title": "Funded paper",
                    "source": "openalex",
                    "matched_grant_number": "R01GM123456",
                    "grant_match": {
                        "verified": True,
                        "type": "structured_award_relationship",
                    },
                }
            ],
            "next_cursor": None,
            "has_more": False,
        }
        grants = client.get(
            "/api/search",
            params={
                "query": "R01GM123456",
                "entity_type": "grants",
                "source": "openalex",
            },
        )
        assert grants.status_code == 200
        body = grants.json()
        assert body["entity_type"] == "grants"
        assert body["results"][0]["result_type"] == "work"
        assert body["results"][0]["matched_grant_number"] == "R01GM123456"
        assert body["results"][0]["grant_match"]["verified"] is True


def test_arxiv_works_request_uses_expected_params():
    captured = {}

    async def fake_fetch(*, search_query, start, max_results):
        captured["search_query"] = search_query
        captured["start"] = start
        captured["max_results"] = max_results
        return SAMPLE_ATOM

    with patch.object(arxiv_client, "_fetch_arxiv_atom", side_effect=fake_fetch):
        response = client.get(
            "/api/search",
            params={
                "query": "quantum computing",
                "entity_type": "works",
                "source": "arxiv",
            },
        )

    assert response.status_code == 200
    assert captured["search_query"] == "all:quantum computing"
    assert captured["start"] == 0
    assert captured["max_results"] == 20
    result = response.json()["results"][0]
    assert result["result_id"] == "arxiv:2401.12345"
    assert result["source"] == "arxiv"
    assert result["openalex_id"] is None
    assert result["cited_by_count"] is None
    assert result["work_type"] == "preprint"
    assert result["categories"] == ["cs.AI", "cs.LG"]


def test_arxiv_atom_normalizes_and_strips_version():
    parsed = parse_arxiv_feed(SAMPLE_ATOM)
    assert parsed["total_results"] == 42
    work = parsed["works"][0]
    assert work["result_id"] == "arxiv:2401.12345"
    assert work["source_id"] == "2401.12345"
    assert work["publication_year"] == 2024
    assert work["authors"][0]["name"] == "Alice Example"
    assert extract_arxiv_id("https://arxiv.org/abs/2401.12345v2") == (
        "2401.12345",
        "2",
    )
    assert extract_arxiv_id("hep-th/9901001v1")[0] == "hep-th/9901001"


def test_arxiv_authors_return_unverified_author_names():
    async def fake_fetch(*, search_query, start, max_results):
        assert search_query == 'au:"Geoffrey Hinton"'
        return SAMPLE_ATOM.replace("Alice Example", "Geoffrey Hinton").replace(
            "Bob Example", "Yoshua Bengio"
        )

    with patch.object(arxiv_client, "_fetch_arxiv_atom", side_effect=fake_fetch):
        response = client.get(
            "/api/search",
            params={
                "query": "Geoffrey Hinton",
                "entity_type": "authors",
                "source": "arxiv",
            },
        )

    assert response.status_code == 200
    results = response.json()["results"]
    assert len(results) >= 1
    author = results[0]
    source_records = author.get("source_records") or []
    if source_records:
        # Identity resolution may canonicalize arXiv author-name hits.
        assert author["result_type"] == "author"
        assert author.get("identity_resolution") is not None
        assert any(r.get("provider") == "arxiv" for r in source_records)
    else:
        assert author["result_type"] == "author_name"
        assert author["is_verified_profile"] is False
        assert author["identity_type"] == "paper_metadata_name"
        assert author["openalex_id"] is None
        assert author["orcid"] is None
        assert author["works_count"] is None
        assert author["cited_by_count"] is None
        assert author["primary_institution"] is None
        assert author["matching_papers_count"] >= 1
        assert author["result_id"].startswith("arxiv-author-name:")


def test_arxiv_grants_returns_metadata_matched_papers():
    captured = {}

    async def fake_fetch(*, search_query, start, max_results):
        captured["search_query"] = search_query
        return SAMPLE_ATOM

    with patch.object(arxiv_client, "_fetch_arxiv_atom", side_effect=fake_fetch):
        response = client.get(
            "/api/search",
            params={
                "provider": "arxiv",
                "entity": "grants",
                "q": "R01GM123456",
                "limit": 20,
            },
        )

    assert response.status_code == 200
    assert captured["search_query"] == 'all:"R01GM123456"'
    body = response.json()
    assert body["source"] == "arxiv"
    assert body["entity_type"] == "grants"
    assert body["results"][0]["result_type"] == "work"
    assert body["results"][0]["matched_grant_number"] == "R01GM123456"
    assert body["results"][0]["grant_match"] == {
        "verified": False,
        "type": "metadata_text_match",
    }


def test_provider_registry_routes_only_selected_provider():
    from app.services.search.providers import PROVIDERS
    from app.services.search.search_service import run_search

    assert set(PROVIDERS) == {"openalex", "arxiv"}

    async def run():
        with patch.object(
            PROVIDERS["arxiv"],
            "search_grants",
            new_callable=AsyncMock,
        ) as arxiv_grants:
            with patch.object(
                PROVIDERS["openalex"],
                "search_grants",
                new_callable=AsyncMock,
            ) as openalex_grants:
                arxiv_grants.return_value = {
                    "query": "R01GM123456",
                    "entity_type": "grants",
                    "source": "arxiv",
                    "results": [],
                    "next_cursor": None,
                    "has_more": False,
                }
                await run_search(
                    query="R01GM123456",
                    entity_type="grants",
                    source="arxiv",
                )
                arxiv_grants.assert_awaited_once()
                openalex_grants.assert_not_called()

    asyncio.run(run())


def test_all_source_rejected():
    response = client.get(
        "/api/search",
        params={"query": "quantum", "entity_type": "works", "source": "all"},
    )
    assert response.status_code == 400
    assert "not available" in response.json()["detail"].lower()


def test_arxiv_pagination_tokens():
    token = build_arxiv_cursor(
        entity_type="works",
        query="quantum computing",
        next_start=20,
    )
    assert (
        validate_arxiv_cursor(
            token, entity_type="works", query="quantum computing"
        )
        == 20
    )

    with pytest.raises(Exception):
        validate_arxiv_cursor(
            "not-a-valid-token",
            entity_type="works",
            query="quantum computing",
        )

    mismatched = build_arxiv_cursor(
        entity_type="works",
        query="other",
        next_start=20,
    )
    with pytest.raises(Exception):
        validate_arxiv_cursor(
            mismatched,
            entity_type="works",
            query="quantum computing",
        )


def test_arxiv_pages_are_cached():
    calls = {"count": 0}

    async def fake_fetch(*, search_query, start, max_results):
        calls["count"] += 1
        return SAMPLE_ATOM

    with patch.object(arxiv_client, "_fetch_arxiv_atom", side_effect=fake_fetch):
        first = client.get(
            "/api/search",
            params={
                "query": "quantum computing",
                "entity_type": "works",
                "source": "arxiv",
            },
        )
        second = client.get(
            "/api/search",
            params={
                "query": "quantum computing",
                "entity_type": "works",
                "source": "arxiv",
            },
        )

    assert first.status_code == 200
    assert second.status_code == 200
    assert calls["count"] == 1


def test_arxiv_rate_control_serializes_uncached_requests():
    events: list[str] = []

    class FakeResponse:
        status_code = 200
        text = SAMPLE_ATOM

    class FakeClient:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return False

        async def get(self, *args, **kwargs):
            events.append("start")
            await asyncio.sleep(0.05)
            events.append("end")
            return FakeResponse()

    async def run_parallel():
        reset_arxiv_client_state_for_tests()
        with patch.object(arxiv_client, "httpx") as mock_httpx:
            mock_httpx.AsyncClient = FakeClient
            mock_httpx.TimeoutException = Exception
            mock_httpx.HTTPError = Exception
            with patch.object(arxiv_client, "MIN_REQUEST_INTERVAL_SECONDS", 0):
                await asyncio.gather(
                    arxiv_client.search_arxiv_works(query="alpha beta"),
                    arxiv_client.search_arxiv_works(query="gamma delta"),
                )

    asyncio.run(run_parallel())
    assert events == ["start", "end", "start", "end"]


def test_openalex_not_delayed_by_arxiv_limiter():
    order: list[str] = []

    class FakeResponse:
        status_code = 200
        text = SAMPLE_ATOM

    class FakeClient:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return False

        async def get(self, *args, **kwargs):
            order.append("arxiv-start")
            await asyncio.sleep(0.1)
            order.append("arxiv-end")
            return FakeResponse()

    async def openalex_search(**kwargs):
        order.append("openalex")
        return {
            "query": kwargs.get("query") or "",
            "entity_type": kwargs.get("entity_type"),
            "source": "openalex",
            "results": [],
            "next_cursor": None,
            "has_more": False,
        }

    async def run():
        reset_arxiv_client_state_for_tests()
        with patch.object(arxiv_client, "httpx") as mock_httpx:
            mock_httpx.AsyncClient = FakeClient
            mock_httpx.TimeoutException = Exception
            mock_httpx.HTTPError = Exception
            with patch.object(arxiv_client, "MIN_REQUEST_INTERVAL_SECONDS", 0):
                with patch(
                    "app.services.search.openalex_provider.unified_openalex_search",
                    side_effect=openalex_search,
                ):
                    from app.services.search.search_service import run_search

                    arxiv_task = asyncio.create_task(
                        run_search(
                            query="quantum computing",
                            entity_type="works",
                            source="arxiv",
                        )
                    )
                    await asyncio.sleep(0.01)
                    openalex_result = await run_search(
                        query="quantum",
                        entity_type="works",
                        source="openalex",
                    )
                    await arxiv_task
                    return openalex_result

    result = asyncio.run(run())
    assert result["source"] == "openalex"
    assert "openalex" in order
    assert order.index("openalex") < order.index("arxiv-end")


def test_capabilities_helper_matches_endpoint():
    payload = get_search_capabilities()
    assert payload["default_source"] == "openalex"
    assert any(item["id"] == "all" and item["enabled"] is False for item in payload["sources"])


def test_normalize_work_rejects_missing_title():
    class Entry:
        id = "http://arxiv.org/abs/2401.99999"
        title = "   "
        summary = ""
        published = None
        updated = None
        authors = []
        author = ""
        tags = []
        links = []
        link = None

    assert normalize_arxiv_work(Entry()) is None
