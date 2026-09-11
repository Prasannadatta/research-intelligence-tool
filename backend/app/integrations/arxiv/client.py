"""arXiv Atom API client with pacing, caching, and opaque cursors."""

from __future__ import annotations

import asyncio
import base64
import json
import time
from collections import OrderedDict
from threading import Lock
from typing import Any

import httpx

from app.core.config import get_settings
from app.integrations.rate_limited_http import provider_get
from app.integrations.arxiv.parser import (
    aggregate_arxiv_author_names,
    author_name_matches_query,
    normalize_arxiv_query,
    normalize_author_name_for_id,
    parse_arxiv_feed,
)


class ArxivApiError(Exception):
    """Raised when arXiv search fails or is misconfigured."""

    def __init__(self, message: str, *, status_code: int = 502) -> None:
        super().__init__(message)
        self.status_code = status_code


PAGE_SIZE = 20
MIN_REQUEST_INTERVAL_SECONDS = 3.0
REQUEST_TIMEOUT_SECONDS = 20.0
CACHE_TTL_SECONDS = 12 * 60 * 60
CACHE_MAX_ENTRIES = 1000


class _TtlCache:
    def __init__(self, *, ttl_seconds: int, max_entries: int) -> None:
        self._ttl_seconds = ttl_seconds
        self._max_entries = max_entries
        self._store: OrderedDict[str, tuple[float, Any]] = OrderedDict()
        self._lock = Lock()

    def get(self, key: str) -> Any | None:
        now = time.monotonic()
        with self._lock:
            item = self._store.get(key)
            if item is None:
                return None
            expires_at, value = item
            if expires_at <= now:
                self._store.pop(key, None)
                return None
            self._store.move_to_end(key)
            return value

    def set(self, key: str, value: Any) -> None:
        expires_at = time.monotonic() + self._ttl_seconds
        with self._lock:
            if key in self._store:
                self._store.move_to_end(key)
            self._store[key] = (expires_at, value)
            while len(self._store) > self._max_entries:
                self._store.popitem(last=False)

    def clear(self) -> None:
        with self._lock:
            self._store.clear()


_page_cache = _TtlCache(ttl_seconds=CACHE_TTL_SECONDS, max_entries=CACHE_MAX_ENTRIES)
_last_uncached_request_at = 0.0


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


def validate_arxiv_cursor(
    cursor: str | None,
    *,
    entity_type: str,
    query: str,
) -> int:
    """
    Return the next start offset from an opaque cursor.

    First page (None/"*") → 0. Rejects malformed or mismatched tokens.
    """
    if cursor is None or cursor == "" or cursor == "*":
        return 0

    payload = _decode_cursor(cursor)
    if not payload:
        raise ArxivApiError("Invalid pagination cursor.", status_code=422)

    if payload.get("provider") != "arxiv":
        raise ArxivApiError("Invalid pagination cursor.", status_code=422)
    if payload.get("entity_type") != entity_type:
        raise ArxivApiError("Invalid pagination cursor.", status_code=422)
    if payload.get("query") != query:
        raise ArxivApiError("Invalid pagination cursor.", status_code=422)

    try:
        start = int(payload.get("start"))
    except (TypeError, ValueError) as exc:
        raise ArxivApiError("Invalid pagination cursor.", status_code=422) from exc

    if start < 0:
        raise ArxivApiError("Invalid pagination cursor.", status_code=422)
    return start


def build_arxiv_cursor(
    *,
    entity_type: str,
    query: str,
    next_start: int,
) -> str:
    return _encode_cursor(
        {
            "provider": "arxiv",
            "entity_type": entity_type,
            "query": query,
            "start": next_start,
        }
    )


def _cache_key(*, entity_type: str, query: str, start: int) -> str:
    return "|".join(["arxiv", entity_type, query, str(start)])


def reset_arxiv_client_state_for_tests() -> None:
    """Test helper: clear cache and rate-limit timestamp."""
    global _last_uncached_request_at
    _page_cache.clear()
    _last_uncached_request_at = 0.0


async def _fetch_arxiv_atom(
    *,
    search_query: str | None = None,
    id_list: str | None = None,
    start: int = 0,
    max_results: int = PAGE_SIZE,
) -> str:
    """Fetch Atom XML with process-wide pacing for uncached requests."""
    global _last_uncached_request_at

    settings = get_settings()
    if not settings.arxiv_configured:
        raise ArxivApiError(
            "arXiv search is temporarily unavailable. Please try again.",
            status_code=503,
        )

    params: dict[str, Any] = {
        "start": start,
        "max_results": max_results,
    }
    if id_list:
        params["id_list"] = id_list
    else:
        params["search_query"] = search_query or ""
        params["sortBy"] = "relevance"
        params["sortOrder"] = "descending"
    headers = {
        "User-Agent": settings.arxiv_user_agent,
        "Accept": "application/atom+xml, application/xml, text/xml, */*",
    }

    try:
        response = await provider_get(
            "arxiv",
            settings.arxiv_base_url,
            params=params,
            timeout=REQUEST_TIMEOUT_SECONDS,
            follow_redirects=True,
            headers=headers,
        )
    except httpx.TimeoutException as exc:
        raise ArxivApiError(
            "arXiv search is temporarily unavailable. Please try again."
        ) from exc
    except httpx.HTTPError as exc:
        raise ArxivApiError(
            "arXiv search is temporarily unavailable. Please try again."
        ) from exc
    finally:
        _last_uncached_request_at = time.monotonic()

    if response.status_code == 429:
        raise ArxivApiError(
            "arXiv rate limit reached.",
            status_code=429,
        )
    if response.status_code == 503:
        raise ArxivApiError(
            "arXiv search is temporarily unavailable. Please try again.",
            status_code=503,
        )
    if response.status_code >= 500:
        raise ArxivApiError(
            "arXiv search is temporarily unavailable. Please try again."
        )
    if response.status_code >= 400:
        raise ArxivApiError(
            "arXiv rejected the search request.",
            status_code=502,
        )

    return response.text


async def _get_parsed_page(
    *,
    entity_type: str,
    query: str,
    search_query: str,
    start: int,
) -> dict[str, Any]:
    key = _cache_key(entity_type=entity_type, query=query, start=start)
    cached = _page_cache.get(key)
    if cached is not None:
        return cached

    xml_text = await _fetch_arxiv_atom(
        search_query=search_query,
        start=start,
        max_results=PAGE_SIZE,
    )
    parsed = parse_arxiv_feed(xml_text)
    _page_cache.set(key, parsed)
    return parsed


async def fetch_arxiv_works_by_ids(
    arxiv_ids: list[str],
    *,
    max_results: int | None = None,
) -> list[dict[str, Any]]:
    """Fetch preprint metadata for known arXiv IDs (enrich-only; no author crawl).

    Uses the Atom `id_list` API. Results are cached in-process by id set.
    """
    from app.integrations.arxiv.parser import extract_arxiv_id
    from app.services.work_persistence.normalization import normalize_arxiv_id

    cleaned: list[str] = []
    seen: set[str] = set()
    for value in arxiv_ids:
        normalized = normalize_arxiv_id(value)
        if not normalized:
            bare, _version = extract_arxiv_id(value)
            normalized = normalize_arxiv_id(bare) if bare else None
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        cleaned.append(normalized)
    if not cleaned:
        return []

    page_size = max(1, min(int(max_results or len(cleaned)), 50))
    cache_key = _cache_key(
        entity_type="work_by_id",
        query=",".join(cleaned),
        start=0,
    )
    cached = _page_cache.get(cache_key)
    if cached is not None:
        return list(cached.get("results") or [])

    xml_text = await _fetch_arxiv_atom(
        id_list=",".join(cleaned),
        start=0,
        max_results=page_size,
    )
    parsed = parse_arxiv_feed(xml_text)
    _page_cache.set(cache_key, parsed)
    return list(parsed.get("results") or [])


def _page_has_more(
    *,
    start: int,
    returned_count: int,
    total_results: int | None,
) -> bool:
    if returned_count <= 0:
        return False
    if total_results is not None:
        return (start + returned_count) < total_results
    return returned_count >= PAGE_SIZE


async def search_arxiv_authors(
    *,
    query: str,
    limit: int = PAGE_SIZE,
    cursor: str | None = None,
) -> dict[str, Any]:
    cleaned = normalize_arxiv_query(query)
    if len(cleaned) < 3:
        raise ArxivApiError(
            "Query must be at least 3 characters after trimming.",
            status_code=422,
        )

    page_size = max(1, min(int(limit or PAGE_SIZE), PAGE_SIZE))
    start = validate_arxiv_cursor(cursor, entity_type="authors", query=cleaned)
    # Quote the author query for the au: field.
    escaped = cleaned.replace('"', "")
    search_query = f'au:"{escaped}"'

    parsed = await _get_parsed_page(
        entity_type="authors",
        query=cleaned,
        search_query=search_query,
        start=start,
    )
    works = list(parsed.get("works") or [])
    authors = aggregate_arxiv_author_names(works, query=cleaned)[:page_size]
    total_results = parsed.get("total_results")
    # Author aggregation is derived from this paper page; has_more follows paper paging.
    has_more = _page_has_more(
        start=start,
        returned_count=len(works),
        total_results=total_results if isinstance(total_results, int) else None,
    )
    next_cursor = (
        build_arxiv_cursor(
            entity_type="authors",
            query=cleaned,
            next_start=start + PAGE_SIZE,
        )
        if has_more
        else None
    )

    return {
        "query": cleaned,
        "entity_type": "authors",
        "source": "arxiv",
        "results": authors,
        "next_cursor": next_cursor,
        "has_more": has_more,
    }


def _escape_au_term(name: str) -> str:
    return " ".join((name or "").split()).replace('"', "")


def paper_contains_all_author_names(
    work: dict[str, Any],
    author_names: list[str],
) -> bool:
    """
    Require every selected display name to appear in the paper author list.

    Uses the same conservative token match as experimental arXiv author search.
    Does not claim verified author identity.
    """
    authors = work.get("authors") if isinstance(work.get("authors"), list) else []
    paper_names = [
        str(author.get("name") or "").strip()
        for author in authors
        if isinstance(author, dict) and str(author.get("name") or "").strip()
    ]
    if not paper_names:
        return False

    for required in author_names:
        cleaned = " ".join((required or "").split())
        if not cleaned:
            return False
        if not any(author_name_matches_query(paper_name, cleaned) for paper_name in paper_names):
            return False
    return True


def _annotate_arxiv_analysis_work(work: dict[str, Any]) -> dict[str, Any]:
    item = dict(work)
    item["grants"] = list(item.get("grants") or [])
    if item.get("entry_url") and not item.get("url"):
        item["url"] = item["entry_url"]
    if item.get("primary_source") and not item.get("journal"):
        item["journal"] = item["primary_source"]
    if item.get("cited_by_count") is not None:
        item["citation_count"] = item["cited_by_count"]
    return item


async def search_arxiv_publications_by_authors(
    *,
    author_names: list[str],
    limit: int = PAGE_SIZE,
    cursor: str | None = None,
) -> dict[str, Any]:
    """
    Experimental arXiv publication search by author display names.

    Single author: au:"Name" paper search.
    Multiple authors: AND of au: clauses, then verify every selected name
    appears in each paper's author list. Results are unverified identity matches.
    """
    cleaned_names: list[str] = []
    seen_keys: set[str] = set()
    for name in author_names:
        cleaned = " ".join((name or "").split())
        if len(cleaned) < 2:
            continue
        key = normalize_author_name_for_id(cleaned)
        if not key or key in seen_keys:
            continue
        seen_keys.add(key)
        cleaned_names.append(cleaned)

    if not cleaned_names:
        raise ArxivApiError(
            "At least one author display name is required for arXiv analysis.",
            status_code=422,
        )

    # Stable query key for cursor validation / cache.
    query_key = " && ".join(cleaned_names)
    page_size = max(1, min(int(limit or PAGE_SIZE), PAGE_SIZE))
    start = validate_arxiv_cursor(cursor, entity_type="author_publications", query=query_key)

    au_clauses = [f'au:"{_escape_au_term(name)}"' for name in cleaned_names]
    search_query = " AND ".join(au_clauses)

    parsed = await _get_parsed_page(
        entity_type="author_publications",
        query=query_key,
        search_query=search_query,
        start=start,
    )
    works = list(parsed.get("works") or [])
    results: list[dict[str, Any]] = []
    for work in works:
        if not isinstance(work, dict):
            continue
        if not paper_contains_all_author_names(work, cleaned_names):
            continue
        results.append(_annotate_arxiv_analysis_work(work))
        if len(results) >= page_size:
            break

    total_results = parsed.get("total_results")
    has_more = _page_has_more(
        start=start,
        returned_count=len(works),
        total_results=total_results if isinstance(total_results, int) else None,
    )
    next_cursor = (
        build_arxiv_cursor(
            entity_type="author_publications",
            query=query_key,
            next_start=start + PAGE_SIZE,
        )
        if has_more
        else None
    )

    count = total_results if isinstance(total_results, int) and total_results >= 0 else None
    return {
        "query": query_key,
        "entity_type": "works",
        "source": "arxiv",
        "author_names": cleaned_names,
        "results": results[:page_size],
        "next_cursor": next_cursor,
        "has_more": has_more,
        "count": count,
    }


async def search_arxiv_grants(
    *,
    query: str,
    limit: int = PAGE_SIZE,
    cursor: str | None = None,
) -> dict[str, Any]:
    """
    Grants mode for arXiv: search paper metadata for the grant/award number.

    Returns publication/work rows only (never grant/award records).
    Matches are unverified metadata text hits.
    """
    cleaned = normalize_arxiv_query(query)
    if not cleaned:
        raise ArxivApiError("Query is required.", status_code=422)
    if len(cleaned) < 2:
        raise ArxivApiError(
            "Grant-number search requires at least 2 characters.",
            status_code=422,
        )

    page_size = max(1, min(int(limit or PAGE_SIZE), PAGE_SIZE))
    start = validate_arxiv_cursor(cursor, entity_type="grants", query=cleaned)
    escaped = cleaned.replace('"', "")
    # Prefer a quoted all: search so identifiers with punctuation match metadata.
    search_query = f'all:"{escaped}"'

    parsed = await _get_parsed_page(
        entity_type="grants",
        query=cleaned,
        search_query=search_query,
        start=start,
    )
    works = list(parsed.get("works") or [])[:page_size]
    results: list[dict[str, Any]] = []
    for work in works:
        item = dict(work)
        item["matched_grant_number"] = cleaned
        item["grant_match"] = {
            "verified": False,
            "type": "metadata_text_match",
        }
        results.append(item)

    total_results = parsed.get("total_results")
    has_more = _page_has_more(
        start=start,
        returned_count=len(works),
        total_results=total_results if isinstance(total_results, int) else None,
    )
    next_cursor = (
        build_arxiv_cursor(
            entity_type="grants",
            query=cleaned,
            next_start=start + page_size,
        )
        if has_more
        else None
    )

    return {
        "query": cleaned,
        "entity_type": "grants",
        "source": "arxiv",
        "results": results,
        "next_cursor": next_cursor,
        "has_more": has_more,
    }
