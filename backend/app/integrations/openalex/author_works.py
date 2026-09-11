"""OpenAlex works queries scoped to one or more author IDs."""

from __future__ import annotations

from typing import Any

from app.integrations.openalex.client import (
    OpenAlexApiError,
    _as_optional_int,
    _openalex_get,
    _require_api_key,
    _short_openalex_id,
    is_valid_openalex_author_id,
)
from app.integrations.openalex.unified_search import (
    DEFAULT_PAGE_SIZE,
    MAX_PAGE_SIZE,
    OPENALEX_WORKS_URL,
    _optional_str,
    normalize_search_work,
)


def _normalize_author_ids(author_ids: list[str]) -> list[str]:
    cleaned: list[str] = []
    seen: set[str] = set()
    for raw in author_ids:
        short = _short_openalex_id(raw) or str(raw or "").strip()
        if not short or not is_valid_openalex_author_id(short):
            continue
        if short in seen:
            continue
        seen.add(short)
        cleaned.append(short)
    return cleaned


def build_author_id_filter(author_ids: list[str]) -> str:
    """
    Build an OpenAlex Works filter requiring every author ID.

    Comma-separated filters are ANDed by OpenAlex.
    Equivalent to one ID per group in :func:`build_grouped_author_id_filter`.
    """
    return build_grouped_author_id_filter([[author_id] for author_id in author_ids])


def build_grouped_author_id_filter(author_id_groups: list[list[str]]) -> str:
    """
    Build an OpenAlex Works filter from per-author ID groups.

    Within a group, IDs are ORed (``|``) so a canonical author with multiple
    linked OpenAlex records contributes a union of their works.
    Across groups, filters are ANDed (``,``) so multi-author analysis returns
    the intersection of co-authored works.
    """
    if not author_id_groups:
        raise OpenAlexApiError(
            "At least one valid OpenAlex author ID is required.",
            status_code=422,
        )

    parts: list[str] = []
    for group in author_id_groups:
        ids = _normalize_author_ids(group)
        if not ids:
            raise OpenAlexApiError(
                "At least one valid OpenAlex author ID is required.",
                status_code=422,
            )
        if len(ids) == 1:
            parts.append(f"author.id:{ids[0]}")
        else:
            parts.append(f"author.id:{'|'.join(ids)}")
    return ",".join(parts)


def extract_grants_from_openalex_work(work: dict[str, Any]) -> list[dict[str, Any]]:
    """Structured award relationships from an OpenAlex work payload."""
    awards = work.get("awards")
    if not isinstance(awards, list):
        return []

    grants: list[dict[str, Any]] = []
    seen: set[str] = set()
    for award in awards:
        if not isinstance(award, dict):
            continue
        award_id = _optional_str(award.get("funder_award_id"))
        funder_name = None
        funder = award.get("funder")
        if isinstance(funder, dict):
            funder_name = _optional_str(funder.get("display_name"))
        if not funder_name:
            funder_name = _optional_str(award.get("funder_display_name"))

        key = (award_id or "") + "|" + (funder_name or "")
        if not award_id and not funder_name:
            continue
        if key in seen:
            continue
        seen.add(key)
        grants.append(
            {
                "award_id": award_id,
                "funder_name": funder_name,
                "verified": True,
                "match_type": "structured_award_relationship",
                "provider": "openalex",
            }
        )
    return grants


def _work_url(work: dict[str, Any], normalized: dict[str, Any]) -> str | None:
    primary = work.get("primary_location")
    if isinstance(primary, dict):
        landing = _optional_str(primary.get("landing_page_url"))
        if landing:
            return landing
    doi = normalized.get("doi")
    if doi:
        return f"https://doi.org/{doi}"
    openalex_id = normalized.get("openalex_id")
    if openalex_id:
        return f"https://openalex.org/{openalex_id}"
    return None


def _normalize_work_with_grants(work: dict[str, Any]) -> dict[str, Any] | None:
    normalized = normalize_search_work(work)
    if normalized is None:
        return None
    grants = extract_grants_from_openalex_work(work)
    normalized["grants"] = grants
    url = _work_url(work, normalized)
    if url:
        normalized["url"] = url
    # Keep journal alias aligned with Work card / analysis response.
    if normalized.get("primary_source") and not normalized.get("journal"):
        normalized["journal"] = normalized["primary_source"]
    if normalized.get("cited_by_count") is not None:
        normalized["citation_count"] = normalized["cited_by_count"]
    return normalized


async def search_works_by_author_ids(
    *,
    author_ids: list[str] | None = None,
    author_id_groups: list[list[str]] | None = None,
    limit: int = DEFAULT_PAGE_SIZE,
    cursor: str | None = None,
) -> dict[str, Any]:
    """
    Query OpenAlex Works for publications scoped to author ID(s).

    ``author_ids``: each ID is required (AND) — typical multi-author intersection.
    ``author_id_groups``: each group is OR'd; groups are AND'd — use when a
    canonical author may have multiple linked OpenAlex author records.
    """
    if author_id_groups is not None:
        groups = author_id_groups
        filter_value = build_grouped_author_id_filter(groups)
        flat_ids = [
            author_id
            for group in groups
            for author_id in _normalize_author_ids(group)
        ]
    else:
        ids = _normalize_author_ids(author_ids or [])
        if not ids:
            raise OpenAlexApiError(
                "At least one valid OpenAlex author ID is required.",
                status_code=422,
            )
        groups = [[author_id] for author_id in ids]
        filter_value = build_author_id_filter(ids)
        flat_ids = ids

    page_size = max(1, min(int(limit or DEFAULT_PAGE_SIZE), MAX_PAGE_SIZE))
    request_cursor = (cursor or "").strip() or "*"
    api_key = _require_api_key()

    params: dict[str, Any] = {
        "filter": filter_value,
        "per_page": page_size,
        "cursor": request_cursor,
        "api_key": api_key,
    }

    response = await _openalex_get(OPENALEX_WORKS_URL, params=params)

    if response.status_code == 429:
        raise OpenAlexApiError(
            "OpenAlex rate limit reached.",
            status_code=429,
        )
    if response.status_code >= 500:
        raise OpenAlexApiError("OpenAlex works search is temporarily unavailable.")
    if response.status_code >= 400:
        raise OpenAlexApiError(
            "OpenAlex rejected the author works request.",
            status_code=502,
        )

    try:
        payload = response.json()
    except ValueError as exc:
        raise OpenAlexApiError("OpenAlex returned an invalid response.") from exc

    if not isinstance(payload, dict):
        raise OpenAlexApiError("OpenAlex returned an invalid response.")

    raw_results = payload.get("results")
    results_list = raw_results if isinstance(raw_results, list) else []
    normalized: list[dict[str, Any]] = []
    for item in results_list:
        if not isinstance(item, dict):
            continue
        row = _normalize_work_with_grants(item)
        if row is not None:
            normalized.append(row)

    meta = payload.get("meta") if isinstance(payload.get("meta"), dict) else {}
    next_cursor = _optional_str(meta.get("next_cursor"))
    has_more = bool(next_cursor) and len(results_list) > 0
    count = _as_optional_int(meta.get("count"))

    return {
        "entity_type": "works",
        "source": "openalex",
        "author_ids": flat_ids,
        "author_id_groups": [
            _normalize_author_ids(group) for group in groups
        ],
        "results": normalized,
        "next_cursor": next_cursor,
        "has_more": has_more,
        "count": count if count is not None and count >= 0 else None,
    }
