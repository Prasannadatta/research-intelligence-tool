"""Grant-number search flows against OpenAlex Awards and funded Works."""

from __future__ import annotations

import base64
import json
from typing import Any

from app.integrations.openalex.client import (
    OpenAlexApiError,
    _openalex_get,
    _require_api_key,
    _short_openalex_id,
)
from app.integrations.openalex.grant_number import (
    NormalizedGrantNumber,
    grant_number_match_rank,
    normalize_grant_number,
)
from app.integrations.openalex.unified_search import (
    DEFAULT_PAGE_SIZE,
    MAX_PAGE_SIZE,
    OPENALEX_AWARDS_URL,
    OPENALEX_WORKS_URL,
    normalize_search_author,
    normalize_search_grant,
    normalize_search_work,
    _optional_str,
)

MAX_RESOLVED_AWARDS = 8
MAX_WORKS_FOR_AUTHOR_AGGREGATION = 100
AUTHOR_WORKS_PAGE_SIZE = 50


def _award_summary(award: dict[str, Any]) -> dict[str, Any]:
    funder_name = None
    funder = award.get("funder")
    if isinstance(funder, dict):
        funder_name = _optional_str(funder.get("display_name"))
    return {
        "award_id": _optional_str(award.get("funder_award_id")),
        "display_name": _optional_str(award.get("display_name")),
        "funder_name": funder_name,
        "openalex_id": _short_openalex_id(award.get("id")),
    }


async def _get_json(url: str, params: dict[str, Any]) -> dict[str, Any]:
    response = await _openalex_get(url, params=params)
    if response.status_code >= 500:
        raise OpenAlexApiError("OpenAlex search is temporarily unavailable.")
    if response.status_code >= 400:
        raise OpenAlexApiError(
            "OpenAlex rejected the grant-number search request.",
            status_code=502,
        )
    try:
        payload = response.json()
    except ValueError as exc:
        raise OpenAlexApiError("OpenAlex returned an invalid response.") from exc
    if not isinstance(payload, dict):
        raise OpenAlexApiError("OpenAlex returned an invalid response.")
    return payload


async def resolve_awards_for_grant_number(
    grant: NormalizedGrantNumber,
    *,
    limit: int = MAX_RESOLVED_AWARDS,
) -> list[dict[str, Any]]:
    """Resolve OpenAlex Award records for a grant/award number."""
    api_key = _require_api_key()
    exact: list[dict[str, Any]] = []
    seen: set[str] = set()

    for candidate in (grant.compact, grant.normalized):
        if not candidate:
            continue
        payload = await _get_json(
            OPENALEX_AWARDS_URL,
            {
                "filter": f"funder_award_id:{candidate}",
                "per_page": min(limit, 20),
                "api_key": api_key,
            },
        )
        for item in payload.get("results") or []:
            if not isinstance(item, dict):
                continue
            openalex_id = _short_openalex_id(item.get("id"))
            if not openalex_id or openalex_id in seen:
                continue
            seen.add(openalex_id)
            exact.append(item)

    # Textual / close matches via award search.
    search_payload = await _get_json(
        OPENALEX_AWARDS_URL,
        {
            "search": grant.normalized,
            "per_page": min(max(limit * 2, 10), 25),
            "api_key": api_key,
        },
    )
    textual: list[tuple[int, dict[str, Any]]] = []
    for item in search_payload.get("results") or []:
        if not isinstance(item, dict):
            continue
        openalex_id = _short_openalex_id(item.get("id"))
        if not openalex_id or openalex_id in seen:
            continue
        rank = grant_number_match_rank(item.get("funder_award_id"), grant)
        textual.append((rank, item))

    textual.sort(key=lambda pair: (-pair[0], -(pair[1].get("funded_outputs_count") or 0)))
    combined = exact + [item for _, item in textual]
    return combined[:limit]


def _encode_cursor(payload: dict[str, Any]) -> str:
    raw = json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8")
    return base64.urlsafe_b64encode(raw).decode("ascii")


def _decode_cursor(cursor: str | None) -> dict[str, Any] | None:
    if not cursor or cursor == "*":
        return None
    try:
        raw = base64.urlsafe_b64decode(cursor.encode("ascii"))
        payload = json.loads(raw.decode("utf-8"))
    except (ValueError, json.JSONDecodeError, UnicodeError):
        return None
    return payload if isinstance(payload, dict) else None


async def search_grants_by_grant_number(
    *,
    query: str,
    limit: int = DEFAULT_PAGE_SIZE,
    cursor: str | None = None,
) -> dict[str, Any]:
    grant = normalize_grant_number(query)
    page_size = max(1, min(int(limit or DEFAULT_PAGE_SIZE), MAX_PAGE_SIZE))
    offset = 0
    decoded = _decode_cursor(cursor)
    if decoded and decoded.get("mode") == "grant_awards":
        offset = max(int(decoded.get("offset") or 0), 0)

    awards = await resolve_awards_for_grant_number(grant, limit=max(page_size * 3, 20))
    # Exact identifier matches first, then remaining by match rank / funded outputs.
    ranked: list[tuple[int, dict[str, Any]]] = []
    for award in awards:
        rank = grant_number_match_rank(award.get("funder_award_id"), grant)
        if rank >= 90:
            rank += 20
        ranked.append((rank, award))
    ranked.sort(key=lambda pair: (-pair[0], -(pair[1].get("funded_outputs_count") or 0)))

    page_items = [award for _, award in ranked[offset : offset + page_size]]
    results: list[dict[str, Any]] = []
    for award in page_items:
        normalized = normalize_search_grant(award)
        if normalized is None:
            continue
        normalized["match_reason"] = "grant_number"
        normalized["matched_grant"] = _award_summary(award)
        results.append(normalized)

    next_offset = offset + page_size
    has_more = next_offset < len(ranked)
    next_cursor = (
        _encode_cursor({"mode": "grant_awards", "offset": next_offset, "q": grant.compact})
        if has_more
        else None
    )
    return {
        "query": grant.normalized,
        "entity_type": "grants",
        "source": "openalex",
        "search_mode": "grant_number",
        "results": results,
        "next_cursor": next_cursor,
        "has_more": has_more,
    }


async def search_publications_for_grant_number(
    *,
    query: str,
    limit: int = DEFAULT_PAGE_SIZE,
    cursor: str | None = None,
) -> dict[str, Any]:
    """
    Grants UI mode: treat query as a funder award ID and return linked Works.

    Uses OpenAlex Works filter awards.funder_award_id:<grant number> directly.
    Does not return Award objects and does not fuzzy-match.
    """
    cleaned = " ".join((query or "").split())
    if not cleaned:
        raise OpenAlexApiError(
            "Query is required.",
            status_code=422,
        )
    if len(cleaned) < 2:
        raise OpenAlexApiError(
            "Grant-number search requires at least 2 characters.",
            status_code=422,
        )

    page_size = max(1, min(int(limit or DEFAULT_PAGE_SIZE), MAX_PAGE_SIZE))
    request_cursor = (cursor or "").strip() or "*"
    api_key = _require_api_key()

    payload = await _get_json(
        OPENALEX_WORKS_URL,
        {
            "filter": f"awards.funder_award_id:{cleaned}",
            "per_page": page_size,
            "cursor": request_cursor,
            "api_key": api_key,
        },
    )

    raw_results = payload.get("results") if isinstance(payload.get("results"), list) else []
    results: list[dict[str, Any]] = []
    for work in raw_results:
        if not isinstance(work, dict):
            continue
        normalized = normalize_search_work(work)
        if normalized is None:
            continue
        normalized["matched_grant_number"] = cleaned
        normalized["grant_match"] = {
            "verified": True,
            "type": "structured_award_relationship",
        }
        results.append(normalized)

    meta = payload.get("meta") if isinstance(payload.get("meta"), dict) else {}
    next_cursor = _optional_str(meta.get("next_cursor"))
    has_more = bool(next_cursor) and len(raw_results) > 0

    return {
        "query": cleaned,
        "entity_type": "grants",
        "source": "openalex",
        "results": results,
        "next_cursor": next_cursor,
        "has_more": has_more,
    }


def _works_award_filter(awards: list[dict[str, Any]], grant: NormalizedGrantNumber) -> str | None:
    award_ids = [
        _short_openalex_id(award.get("id"))
        for award in awards
        if _short_openalex_id(award.get("id"))
    ]
    award_ids = [aid for aid in award_ids if aid]
    if award_ids:
        # OpenAlex OR syntax within one filter value.
        return "awards.id:" + "|".join(award_ids[:MAX_RESOLVED_AWARDS])

    # Fallback to funder award id when OpenAlex IDs are unavailable.
    if grant.compact:
        return f"awards.funder_award_id:{grant.compact}"
    return None


def _best_matched_grant_for_work(
    work: dict[str, Any],
    awards: list[dict[str, Any]],
    grant: NormalizedGrantNumber,
) -> dict[str, Any] | None:
    summaries = [_award_summary(award) for award in awards]
    by_id = {
        summary["openalex_id"]: summary
        for summary in summaries
        if summary.get("openalex_id")
    }

    work_awards = work.get("awards")
    if isinstance(work_awards, list):
        best = None
        best_rank = -1
        for item in work_awards:
            if not isinstance(item, dict):
                continue
            openalex_id = _short_openalex_id(item.get("id"))
            rank = grant_number_match_rank(item.get("funder_award_id"), grant)
            if openalex_id and openalex_id in by_id and rank > best_rank:
                best = by_id[openalex_id]
                best_rank = rank
            elif rank > best_rank:
                best = {
                    "award_id": _optional_str(item.get("funder_award_id")),
                    "display_name": _optional_str(item.get("display_name")),
                    "funder_name": _optional_str(item.get("funder_display_name")),
                    "openalex_id": openalex_id,
                }
                best_rank = rank
        if best:
            return best

    return summaries[0] if summaries else None


async def search_works_by_grant_number(
    *,
    query: str,
    limit: int = DEFAULT_PAGE_SIZE,
    cursor: str | None = None,
) -> dict[str, Any]:
    grant = normalize_grant_number(query)
    page_size = max(1, min(int(limit or DEFAULT_PAGE_SIZE), MAX_PAGE_SIZE))
    request_cursor = (cursor or "").strip() or "*"

    awards = await resolve_awards_for_grant_number(grant)
    if not awards:
        return {
            "query": grant.normalized,
            "entity_type": "works",
            "source": "openalex",
            "search_mode": "grant_number",
            "results": [],
            "next_cursor": None,
            "has_more": False,
        }

    works_filter = _works_award_filter(awards, grant)
    if not works_filter:
        return {
            "query": grant.normalized,
            "entity_type": "works",
            "source": "openalex",
            "search_mode": "grant_number",
            "results": [],
            "next_cursor": None,
            "has_more": False,
        }

    api_key = _require_api_key()
    payload = await _get_json(
        OPENALEX_WORKS_URL,
        {
            "filter": works_filter,
            "per_page": page_size,
            "cursor": request_cursor,
            "api_key": api_key,
        },
    )
    raw_results = payload.get("results") if isinstance(payload.get("results"), list) else []
    results: list[dict[str, Any]] = []
    for work in raw_results:
        if not isinstance(work, dict):
            continue
        normalized = normalize_search_work(work)
        if normalized is None:
            continue
        normalized["match_reason"] = "grant_number"
        normalized["matched_grant"] = _best_matched_grant_for_work(work, awards, grant)
        results.append(normalized)

    meta = payload.get("meta") if isinstance(payload.get("meta"), dict) else {}
    next_cursor = _optional_str(meta.get("next_cursor"))
    has_more = bool(next_cursor) and len(raw_results) > 0
    return {
        "query": grant.normalized,
        "entity_type": "works",
        "source": "openalex",
        "search_mode": "grant_number",
        "results": results,
        "next_cursor": next_cursor,
        "has_more": has_more,
    }


async def _collect_funded_works(
    *,
    awards: list[dict[str, Any]],
    grant: NormalizedGrantNumber,
    max_works: int = MAX_WORKS_FOR_AUTHOR_AGGREGATION,
) -> tuple[list[dict[str, Any]], dict[str, Any] | None]:
    works_filter = _works_award_filter(awards, grant)
    if not works_filter:
        return [], None

    api_key = _require_api_key()
    collected: list[dict[str, Any]] = []
    cursor = "*"
    primary_grant = _award_summary(awards[0]) if awards else None

    while len(collected) < max_works and cursor:
        payload = await _get_json(
            OPENALEX_WORKS_URL,
            {
                "filter": works_filter,
                "per_page": min(AUTHOR_WORKS_PAGE_SIZE, max_works - len(collected)),
                "cursor": cursor,
                "api_key": api_key,
            },
        )
        batch = payload.get("results") if isinstance(payload.get("results"), list) else []
        for work in batch:
            if isinstance(work, dict):
                collected.append(work)
        meta = payload.get("meta") if isinstance(payload.get("meta"), dict) else {}
        cursor = _optional_str(meta.get("next_cursor"))
        if not batch:
            break

    return collected[:max_works], primary_grant


def _aggregate_authors_from_works(
    works: list[dict[str, Any]],
    *,
    primary_grant: dict[str, Any] | None,
) -> list[dict[str, Any]]:
    aggregates: dict[str, dict[str, Any]] = {}

    for work in works:
        authorships = work.get("authorships")
        if not isinstance(authorships, list):
            continue
        seen_in_work: set[str] = set()
        for authorship in authorships:
            if not isinstance(authorship, dict):
                continue
            author = authorship.get("author")
            if not isinstance(author, dict):
                continue
            author_id = _short_openalex_id(author.get("id"))
            if not author_id or author_id in seen_in_work:
                continue
            seen_in_work.add(author_id)

            entry = aggregates.get(author_id)
            if entry is None:
                # Build a lightweight author payload compatible with normalize_search_author.
                lightweight = {
                    "id": author.get("id"),
                    "display_name": author.get("display_name"),
                    "orcid": author.get("orcid"),
                    "display_name_alternatives": [],
                    "affiliations": [],
                    "last_known_institutions": [],
                    "topics": [],
                    "works_count": None,
                    "cited_by_count": None,
                }
                normalized = normalize_search_author(lightweight)
                if normalized is None:
                    continue
                entry = {
                    "author": normalized,
                    "matching_funded_works_count": 0,
                    "authorship_count": 0,
                }
                aggregates[author_id] = entry

            entry["matching_funded_works_count"] += 1
            entry["authorship_count"] += 1

    ranked = sorted(
        aggregates.values(),
        key=lambda item: (
            -item["matching_funded_works_count"],
            -item["authorship_count"],
            item["author"].get("display_name") or "",
        ),
    )

    results: list[dict[str, Any]] = []
    for item in ranked:
        author = dict(item["author"])
        author["match_reason"] = "grant_number"
        author["matching_funded_works_count"] = item["matching_funded_works_count"]
        if primary_grant:
            author["matched_grant"] = primary_grant
        # Keep schema compatibility for dropdown rows that may inspect authors list.
        author.setdefault("alternative_names", [])
        results.append(author)
    return results


async def search_authors_by_grant_number(
    *,
    query: str,
    limit: int = DEFAULT_PAGE_SIZE,
    cursor: str | None = None,
) -> dict[str, Any]:
    grant = normalize_grant_number(query)
    page_size = max(1, min(int(limit or DEFAULT_PAGE_SIZE), MAX_PAGE_SIZE))
    offset = 0
    decoded = _decode_cursor(cursor)
    if decoded and decoded.get("mode") == "grant_authors":
        offset = max(int(decoded.get("offset") or 0), 0)

    awards = await resolve_awards_for_grant_number(grant)
    if not awards:
        return {
            "query": grant.normalized,
            "entity_type": "authors",
            "source": "openalex",
            "search_mode": "grant_number",
            "results": [],
            "next_cursor": None,
            "has_more": False,
        }

    works, primary_grant = await _collect_funded_works(awards=awards, grant=grant)
    ranked_authors = _aggregate_authors_from_works(works, primary_grant=primary_grant)
    page = ranked_authors[offset : offset + page_size]
    next_offset = offset + page_size
    has_more = next_offset < len(ranked_authors)
    next_cursor = (
        _encode_cursor(
            {
                "mode": "grant_authors",
                "offset": next_offset,
                "q": grant.compact,
            }
        )
        if has_more
        else None
    )
    return {
        "query": grant.normalized,
        "entity_type": "authors",
        "source": "openalex",
        "search_mode": "grant_number",
        "results": page,
        "next_cursor": next_cursor,
        "has_more": has_more,
    }
