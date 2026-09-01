"""Provider registry and capability metadata."""

from __future__ import annotations

from typing import Any

from app.services.search.arxiv_provider import ArxivProvider
from app.services.search.base import BaseSearchProvider
from app.services.search.openalex_provider import OpenAlexProvider
from app.services.search.orcid_provider import OrcidProvider

PROVIDERS: dict[str, BaseSearchProvider] = {
    "openalex": OpenAlexProvider(),
    "arxiv": ArxivProvider(),
    "orcid": OrcidProvider(),
}


def get_provider(provider_name: str) -> BaseSearchProvider | None:
    return PROVIDERS.get((provider_name or "").strip().lower())


def get_search_capabilities() -> dict[str, Any]:
    sources = [provider.to_capability_dict() for provider in PROVIDERS.values()]
    supported: set[str] = set()
    for provider in PROVIDERS.values():
        if provider.enabled:
            supported.update(provider.supported_entity_types)
    sources.append(
        {
            "id": "all",
            "label": "All sources",
            "enabled": bool(supported),
            "supported_entity_types": sorted(supported),
        }
    )
    return {
        "default_source": "all" if supported else "openalex",
        "sources": sources,
    }


FALLBACK_CAPABILITIES: dict[str, Any] = {
    "default_source": "all",
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
            "id": "orcid",
            "label": "ORCID",
            "enabled": True,
            "supported_entity_types": ["authors"],
        },
        {
            "id": "all",
            "label": "All sources",
            "enabled": True,
            "supported_entity_types": ["authors", "works", "grants"],
        },
    ],
}
