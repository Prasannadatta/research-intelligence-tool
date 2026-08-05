"""Provider registry and capability metadata."""

from __future__ import annotations

from typing import Any

from app.services.search.arxiv_provider import ArxivProvider
from app.services.search.base import BaseSearchProvider
from app.services.search.openalex_provider import OpenAlexProvider

PROVIDERS: dict[str, BaseSearchProvider] = {
    "openalex": OpenAlexProvider(),
    "arxiv": ArxivProvider(),
}


def get_provider(provider_name: str) -> BaseSearchProvider | None:
    return PROVIDERS.get((provider_name or "").strip().lower())


def get_search_capabilities() -> dict[str, Any]:
    sources = [provider.to_capability_dict() for provider in PROVIDERS.values()]
    sources.append(
        {
            "id": "all",
            "label": "All",
            "enabled": False,
            "supported_entity_types": [],
        }
    )
    return {
        "default_source": "openalex",
        "sources": sources,
    }


FALLBACK_CAPABILITIES: dict[str, Any] = {
    "default_source": "openalex",
    "sources": [
        {
            "id": "openalex",
            "label": "OpenAlex",
            "enabled": True,
            "supported_entity_types": ["authors", "works", "grants"],
        },
        {
            "id": "arxiv",
            "label": "arXiv",
            "enabled": False,
            "supported_entity_types": [],
        },
        {
            "id": "all",
            "label": "All",
            "enabled": False,
            "supported_entity_types": [],
        },
    ],
}
