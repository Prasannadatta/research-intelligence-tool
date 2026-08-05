"""OpenAlex institution and topic filter lookups."""

from __future__ import annotations

import re
from typing import Any

from app.integrations.openalex.client import (
    OpenAlexApiError,
    _as_optional_int,
    _openalex_get,
    _require_api_key,
    _short_openalex_id,
)

OPENALEX_INSTITUTIONS_URL = "https://api.openalex.org/institutions"
OPENALEX_TOPICS_URL = "https://api.openalex.org/topics"

INSTITUTION_ID_PATTERN = re.compile(r"^I\d+$")
TOPIC_ID_PATTERN = re.compile(r"^T\d+$")
MAX_FILTER_RESULTS = 10


def is_valid_institution_id(value: str | None) -> bool:
    return bool(INSTITUTION_ID_PATTERN.fullmatch((value or "").strip()))


def is_valid_topic_id(value: str | None) -> bool:
    return bool(TOPIC_ID_PATTERN.fullmatch((value or "").strip()))


def _optional_str(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def normalize_institution_filter(item: dict[str, Any]) -> dict[str, Any] | None:
    openalex_id = _short_openalex_id(item.get("id"))
    if not openalex_id or not is_valid_institution_id(openalex_id):
        return None
    display_name = _optional_str(item.get("display_name"))
    if not display_name:
        return None
    return {
        "id": openalex_id,
        "display_name": display_name,
        "country_code": _optional_str(item.get("country_code")),
        "type": _optional_str(item.get("type")),
        "works_count": _as_optional_int(item.get("works_count")),
        "source": "openalex",
    }


def normalize_topic_filter(item: dict[str, Any]) -> dict[str, Any] | None:
    openalex_id = _short_openalex_id(item.get("id"))
    if not openalex_id or not is_valid_topic_id(openalex_id):
        return None
    display_name = _optional_str(item.get("display_name"))
    if not display_name:
        return None
    return {
        "id": openalex_id,
        "display_name": display_name,
        "description": _optional_str(item.get("description")),
        "works_count": _as_optional_int(item.get("works_count")),
        "source": "openalex",
    }


async def _search_filter_entities(
    *,
    url: str,
    query: str,
    limit: int,
    normalize,
) -> list[dict[str, Any]]:
    cleaned_query = " ".join((query or "").split())
    if len(cleaned_query) < 2:
        raise OpenAlexApiError(
            "Query must be at least 2 characters after trimming.",
            status_code=422,
        )

    page_size = max(1, min(int(limit or MAX_FILTER_RESULTS), MAX_FILTER_RESULTS))
    api_key = _require_api_key()
    response = await _openalex_get(
        url,
        params={
            "search": cleaned_query,
            "per_page": page_size,
            "api_key": api_key,
        },
    )

    if response.status_code >= 500:
        raise OpenAlexApiError("OpenAlex filter lookup is temporarily unavailable.")
    if response.status_code >= 400:
        raise OpenAlexApiError(
            "OpenAlex rejected the filter lookup request.",
            status_code=502,
        )

    try:
        payload = response.json()
    except ValueError as exc:
        raise OpenAlexApiError("OpenAlex returned an invalid response.") from exc

    results = payload.get("results") if isinstance(payload, dict) else None
    if not isinstance(results, list):
        return []

    normalized: list[dict[str, Any]] = []
    for item in results:
        if not isinstance(item, dict):
            continue
        candidate = normalize(item)
        if candidate is not None:
            normalized.append(candidate)
        if len(normalized) >= page_size:
            break
    return normalized


async def search_institutions(query: str, limit: int = 10) -> list[dict]:
    return await _search_filter_entities(
        url=OPENALEX_INSTITUTIONS_URL,
        query=query,
        limit=limit,
        normalize=normalize_institution_filter,
    )


async def search_topics(query: str, limit: int = 10) -> list[dict]:
    return await _search_filter_entities(
        url=OPENALEX_TOPICS_URL,
        query=query,
        limit=limit,
        normalize=normalize_topic_filter,
    )
