"""ORCID public API v3.0 client (unauthenticated reads)."""

from __future__ import annotations

import logging
import time
from collections import OrderedDict
from threading import Lock
from typing import Any

import httpx

from app.core.config import get_settings
from app.integrations.orcid.normalize import (
    OrcidNormalizeError,
    build_orcid_author_query,
    candidate_from_orcid_payloads,
    normalize_orcid_id,
)
from app.integrations.rate_limited_http import ProviderRequestError, provider_get
from app.services.author_resolution.candidate import AuthorCandidate

logger = logging.getLogger(__name__)

REQUEST_TIMEOUT_SECONDS = 12.0
CACHE_TTL_SECONDS = 12 * 60 * 60
CACHE_MAX_ENTRIES = 1000
DEFAULT_SEARCH_ROWS = 10
MAX_SEARCH_ROWS = 50


class OrcidApiError(Exception):
    """Raised when ORCID public API calls fail or are misconfigured."""

    def __init__(self, message: str, *, status_code: int = 502) -> None:
        super().__init__(message)
        self.status_code = status_code


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


_response_cache = _TtlCache(ttl_seconds=CACHE_TTL_SECONDS, max_entries=CACHE_MAX_ENTRIES)


def reset_orcid_client_state_for_tests() -> None:
    _response_cache.clear()


def orcid_configured() -> bool:
    return bool(get_settings().orcid_configured)


def orcid_headers() -> dict[str, str]:
    settings = get_settings()
    return {
        "Accept": "application/json",
        "User-Agent": settings.orcid_user_agent,
    }


class OrcidClient:
    """Thin ORCID public-API wrapper. Does not send OAuth credentials."""

    def __init__(self, *, request_func=provider_get) -> None:
        self._request_func = request_func

    def _require_configured(self) -> None:
        if not orcid_configured():
            raise OrcidApiError(
                "ORCID search is temporarily unavailable. Please try again.",
                status_code=503,
            )

    def _base_url(self) -> str:
        return get_settings().orcid_public_base_url.rstrip("/")

    async def _get_json(
        self,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        cache_key: str | None = None,
    ) -> dict[str, Any]:
        self._require_configured()
        if cache_key:
            cached = _response_cache.get(cache_key)
            if cached is not None:
                return cached

        url = f"{self._base_url()}{path}"
        try:
            response = await self._request_func(
                "orcid",
                url,
                params=params,
                headers=orcid_headers(),
                timeout=REQUEST_TIMEOUT_SECONDS,
            )
        except httpx.TimeoutException as exc:
            raise OrcidApiError(
                "ORCID search is temporarily unavailable. Please try again."
            ) from exc
        except httpx.HTTPError as exc:
            raise OrcidApiError(
                "ORCID search is temporarily unavailable. Please try again."
            ) from exc
        except ProviderRequestError as exc:
            raise OrcidApiError(
                "ORCID search is temporarily unavailable. Please try again."
            ) from exc

        if response.status_code == 404:
            raise OrcidApiError("ORCID record was not found.", status_code=404)
        if response.status_code in {429, 503}:
            raise OrcidApiError(
                "ORCID search is temporarily unavailable. Please try again.",
                status_code=502,
            )
        if response.status_code >= 500:
            raise OrcidApiError(
                "ORCID search is temporarily unavailable. Please try again."
            )
        if response.status_code >= 400:
            raise OrcidApiError(
                "ORCID rejected the request.",
                status_code=502,
            )

        try:
            payload = response.json()
        except ValueError as exc:
            raise OrcidApiError("ORCID returned an invalid response.") from exc
        if not isinstance(payload, dict):
            payload = {}
        if cache_key:
            _response_cache.set(cache_key, payload)
        return payload

    async def expanded_search(
        self,
        query: str,
        *,
        rows: int = DEFAULT_SEARCH_ROWS,
        start: int = 0,
    ) -> dict[str, Any]:
        cleaned = " ".join((query or "").split())
        if not cleaned:
            raise OrcidApiError("Query is required.", status_code=422)
        page_size = max(1, min(int(rows or DEFAULT_SEARCH_ROWS), MAX_SEARCH_ROWS))
        offset = max(int(start or 0), 0)
        cache_key = f"expanded-search|{cleaned}|{page_size}|{offset}"
        return await self._get_json(
            "/expanded-search/",
            params={"q": cleaned, "rows": str(page_size), "start": str(offset)},
            cache_key=cache_key,
        )

    async def get_person(self, orcid: str) -> dict[str, Any]:
        normalized = normalize_orcid_id(orcid)
        if not normalized:
            raise OrcidApiError("Invalid ORCID identifier.", status_code=422)
        return await self._get_json(
            f"/{normalized}/person",
            cache_key=f"person|{normalized}",
        )

    async def get_employments(self, orcid: str) -> dict[str, Any]:
        normalized = normalize_orcid_id(orcid)
        if not normalized:
            raise OrcidApiError("Invalid ORCID identifier.", status_code=422)
        return await self._get_json(
            f"/{normalized}/employments",
            cache_key=f"employments|{normalized}",
        )

    async def get_works(self, orcid: str) -> dict[str, Any]:
        normalized = normalize_orcid_id(orcid)
        if not normalized:
            raise OrcidApiError("Invalid ORCID identifier.", status_code=422)
        return await self._get_json(
            f"/{normalized}/works",
            cache_key=f"works|{normalized}",
        )


def _empty_search_result(*, query: str, affiliation: str | None = None) -> dict[str, Any]:
    return {
        "query": query,
        "affiliation": affiliation,
        "entity_type": "authors",
        "source": "orcid",
        "results": [],
        "num_found": 0,
        "has_more": False,
    }


async def _enrich_hit(
    client: OrcidClient,
    hit: dict[str, Any],
    *,
    person: dict[str, Any] | None = None,
) -> AuthorCandidate | None:
    orcid = normalize_orcid_id(hit.get("orcid-id"))
    if not orcid:
        return None
    employments = None
    works = None
    if person is None:
        try:
            person = await client.get_person(orcid)
        except OrcidApiError:
            logger.warning("orcid_person_failed orcid=%s", orcid)
            person = None
    try:
        employments = await client.get_employments(orcid)
    except OrcidApiError:
        logger.warning("orcid_employments_failed orcid=%s", orcid)
    try:
        works = await client.get_works(orcid)
    except OrcidApiError:
        logger.warning("orcid_works_failed orcid=%s", orcid)
    return candidate_from_orcid_payloads(
        orcid=orcid,
        search_hit=hit,
        person=person,
        employments_payload=employments,
        works_payload=works,
    )


async def _search_orcid_by_id(
    orcid: str,
    *,
    enrich: bool = True,
    client: OrcidClient | None = None,
) -> dict[str, Any]:
    """Fetch one ORCID person record by iD. Does not use name search."""
    if not orcid_configured():
        logger.info("orcid_id_lookup_skipped reason=not_configured")
        return _empty_search_result(query=orcid)

    client = client or OrcidClient()
    hit = {"orcid-id": orcid}
    try:
        person = await client.get_person(orcid)
    except OrcidApiError as exc:
        if exc.status_code == 404:
            return _empty_search_result(query=orcid)
        logger.warning("orcid_id_lookup_failed orcid=%s", orcid)
        return _empty_search_result(query=orcid)

    if enrich:
        candidate = await _enrich_hit(client, hit, person=person)
    else:
        candidate = candidate_from_orcid_payloads(
            orcid=orcid,
            search_hit=hit,
            person=person,
        )
    if candidate is None:
        return _empty_search_result(query=orcid)
    return {
        "query": orcid,
        "affiliation": None,
        "entity_type": "authors",
        "source": "orcid",
        "results": [candidate],
        "num_found": 1,
        "has_more": False,
    }


async def search_orcid_authors(
    *,
    query: str,
    affiliation: str | None = None,
    limit: int = DEFAULT_SEARCH_ROWS,
    start: int = 0,
    enrich: bool = True,
    client: OrcidClient | None = None,
) -> dict[str, Any]:
    """
    Search ORCID authors via expanded-search, or fetch a record by ORCID iD.

    Failures return an empty result set so callers can keep using OpenAlex/arXiv.
    Candidates are keyed by ORCID iD and are never merged by display name.
    """
    orcid_id = normalize_orcid_id(query)
    if orcid_id:
        return await _search_orcid_by_id(
            orcid_id,
            enrich=enrich,
            client=client,
        )

    try:
        solr_query = build_orcid_author_query(query, affiliation=affiliation)
    except OrcidNormalizeError as exc:
        raise OrcidApiError(str(exc), status_code=422) from exc

    if not orcid_configured():
        logger.info("orcid_search_skipped reason=not_configured")
        return _empty_search_result(query=solr_query, affiliation=affiliation)

    client = client or OrcidClient()
    page_size = max(1, min(int(limit or DEFAULT_SEARCH_ROWS), MAX_SEARCH_ROWS))
    try:
        payload = await client.expanded_search(solr_query, rows=page_size, start=start)
    except OrcidApiError:
        logger.warning("orcid_search_failed query=%s", solr_query)
        return _empty_search_result(query=solr_query, affiliation=affiliation)

    hits = payload.get("expanded-result") or payload.get("result") or []
    if not isinstance(hits, list):
        hits = []
    try:
        num_found = int(payload.get("num-found") or 0)
    except (TypeError, ValueError):
        num_found = len(hits)

    results: list[AuthorCandidate] = []
    seen: set[str] = set()
    for hit in hits:
        if not isinstance(hit, dict):
            continue
        orcid = normalize_orcid_id(hit.get("orcid-id"))
        if not orcid or orcid in seen:
            continue
        seen.add(orcid)
        if enrich:
            candidate = await _enrich_hit(client, hit)
        else:
            candidate = candidate_from_orcid_payloads(orcid=orcid, search_hit=hit)
        if candidate is None:
            continue
        results.append(candidate)

    return {
        "query": solr_query,
        "affiliation": affiliation,
        "entity_type": "authors",
        "source": "orcid",
        "results": results,
        "num_found": num_found,
        "has_more": (start + len(hits)) < num_found if num_found else False,
    }
