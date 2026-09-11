"""OpenAlex search provider with short-lived author-page caching."""

from __future__ import annotations

import time
from collections import OrderedDict
from threading import Lock
from typing import Any

from app.integrations.openalex.unified_search import unified_openalex_search
from app.services.search.base import BaseSearchProvider

# Author typeahead pages are repeated often (debounce / StrictMode / back-nav).
_AUTHOR_PAGE_CACHE_TTL_SECONDS = 5 * 60
_AUTHOR_PAGE_CACHE_MAX_ENTRIES = 256


class _AuthorPageCache:
    def __init__(self, *, ttl_seconds: int, max_entries: int) -> None:
        self._ttl_seconds = ttl_seconds
        self._max_entries = max_entries
        self._store: OrderedDict[str, tuple[float, dict[str, Any]]] = OrderedDict()
        self._lock = Lock()

    def get(self, key: str) -> dict[str, Any] | None:
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

    def set(self, key: str, value: dict[str, Any]) -> None:
        expires_at = time.monotonic() + self._ttl_seconds
        with self._lock:
            self._store[key] = (expires_at, value)
            self._store.move_to_end(key)
            while len(self._store) > self._max_entries:
                self._store.popitem(last=False)


_author_page_cache = _AuthorPageCache(
    ttl_seconds=_AUTHOR_PAGE_CACHE_TTL_SECONDS,
    max_entries=_AUTHOR_PAGE_CACHE_MAX_ENTRIES,
)


def clear_author_page_cache() -> None:
    """Test helper: drop in-process OpenAlex author page cache."""
    with _author_page_cache._lock:
        _author_page_cache._store.clear()


def _author_cache_key(
    *,
    query: str | None,
    cursor: str | None,
    limit: int,
    filters: dict[str, Any],
) -> str:
    return "|".join(
        [
            " ".join(str(query or "").split()).lower(),
            str(cursor or "*"),
            str(limit),
            str(filters.get("institution_id") or ""),
            str(filters.get("topic_id") or ""),
            str(filters.get("search_mode") or "auto"),
        ]
    )


class OpenAlexProvider(BaseSearchProvider):
    id = "openalex"
    label = "OpenAlex"

    @property
    def enabled(self) -> bool:
        return True

    @property
    def supported_entity_types(self) -> tuple[str, ...]:
        return ("authors", "grants")

    async def _run(
        self,
        *,
        entity: str,
        query: str | None,
        cursor: str | None,
        limit: int,
        filters: dict[str, Any],
    ) -> dict[str, Any]:
        return await unified_openalex_search(
            query=query,
            entity_type=entity,
            limit=limit,
            cursor=cursor,
            institution_id=filters.get("institution_id"),
            topic_id=filters.get("topic_id"),
            search_mode=filters.get("search_mode") or "auto",
            source="openalex",
        )

    async def search_authors(
        self,
        *,
        query: str | None,
        cursor: str | None,
        limit: int,
        filters: dict[str, Any],
    ) -> dict[str, Any]:
        key = _author_cache_key(
            query=query, cursor=cursor, limit=limit, filters=filters
        )
        cached = _author_page_cache.get(key)
        if cached is not None:
            return {
                **cached,
                "results": list(cached.get("results") or []),
            }

        payload = await self._run(
            entity="authors",
            query=query,
            cursor=cursor,
            limit=limit,
            filters=filters,
        )
        _author_page_cache.set(key, payload)
        return payload

    async def search_grants(
        self,
        *,
        query: str | None,
        cursor: str | None,
        limit: int,
        filters: dict[str, Any],
    ) -> dict[str, Any]:
        # Structured award-id filter → publication/work rows only.
        return await self._run(
            entity="grants",
            query=query,
            cursor=cursor,
            limit=limit,
            filters=filters,
        )
