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
    # Author UI expects All → OpenAlex → ORCID ordering.
    all_source = {
        "id": "all",
        "label": "All",
        "enabled": bool(supported),
        "supported_entity_types": sorted(supported),
    }
    ordered: list[dict[str, Any]] = [all_source]
    for provider_id in ("openalex", "orcid", "arxiv"):
        match = next((row for row in sources if row.get("id") == provider_id), None)
        if match is not None:
            ordered.append(match)
    for row in sources:
        if row.get("id") not in {"openalex", "orcid", "arxiv"}:
            ordered.append(row)
    return {
        # Author search defaults to All (OpenAlex + ORCID).
        "default_source": "all",
        "sources": ordered,
    }


FALLBACK_CAPABILITIES: dict[str, Any] = {
    "default_source": "all",
    "sources": [
        {
            "id": "all",
            "label": "All",
            "enabled": True,
            "supported_entity_types": ["authors", "grants"],
        },
        {
            "id": "openalex",
            "label": "OpenAlex",
            "enabled": True,
            "supported_entity_types": ["authors", "grants"],
        },
        {
            "id": "orcid",
            "label": "ORCID",
            "enabled": True,
            "supported_entity_types": ["authors"],
        },
        {
            "id": "arxiv",
            "label": "arXiv",
            "enabled": False,
            # Author-search UI hides arXiv; grants remain when the provider is enabled.
            "supported_entity_types": ["grants"],
        },
    ],
}
