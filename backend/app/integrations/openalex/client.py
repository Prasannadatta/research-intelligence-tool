"""OpenAlex author autocomplete and detail retrieval."""

from __future__ import annotations

import re
import time
from collections import OrderedDict
from datetime import UTC, datetime
from threading import Lock
from typing import Any

import httpx

from app.core.config import get_settings
from app.integrations.rate_limited_http import provider_get

OPENALEX_AUTHORS_URL = "https://api.openalex.org/authors"
OPENALEX_AUTOCOMPLETE_AUTHORS_URL = "https://api.openalex.org/autocomplete/authors"
OPENALEX_ID_PREFIX = "https://openalex.org/"
ORCID_URL_PREFIX = "https://orcid.org/"
USER_AGENT = (
    "ResearchIntelligenceTool/0.1 "
    "(CITRIS researcher discovery; mailto:research-intelligence@berkeley.edu)"
)
REQUEST_TIMEOUT_SECONDS = 12.0
MAX_INSTITUTIONS = 3
MAX_TOPICS = 5
MAX_AUTOCOMPLETE_RESULTS = 10
AUTHOR_ID_PATTERN = re.compile(r"^A\d+$")

AUTOCOMPLETE_CACHE_TTL_SECONDS = 12 * 60 * 60
AUTOCOMPLETE_CACHE_MAX_ENTRIES = 1000


class OpenAlexApiError(Exception):
    """Raised when OpenAlex search fails or is misconfigured."""

    def __init__(self, message: str, *, status_code: int = 502) -> None:
        super().__init__(message)
        self.status_code = status_code


class _TtlCache:
    """Simple in-memory TTL cache with a hard entry cap."""

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


_autocomplete_cache = _TtlCache(
    ttl_seconds=AUTOCOMPLETE_CACHE_TTL_SECONDS,
    max_entries=AUTOCOMPLETE_CACHE_MAX_ENTRIES,
)


def normalize_autocomplete_query(query: str) -> str:
    return re.sub(r"\s+", " ", query.strip().lower())


def is_valid_openalex_author_id(openalex_id: str) -> bool:
    return bool(AUTHOR_ID_PATTERN.fullmatch((openalex_id or "").strip()))


def _require_api_key() -> str:
    api_key = (get_settings().openalex_api_key or "").strip()
    if not api_key:
        raise OpenAlexApiError(
            "OpenAlex API key is not configured. Set OPENALEX_API_KEY in the backend environment.",
            status_code=500,
        )
    return api_key


def _short_openalex_id(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    if text.startswith(OPENALEX_ID_PREFIX):
        text = text[len(OPENALEX_ID_PREFIX) :]
    if "/" in text:
        text = text.rstrip("/").rsplit("/", 1)[-1]
    return text or None


def _normalize_orcid(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    if text.startswith(ORCID_URL_PREFIX):
        text = text[len(ORCID_URL_PREFIX) :]
    return text or None


def _as_optional_int(value: Any) -> int | None:
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _institution_from_raw(
    raw: dict[str, Any] | None,
    *,
    relationship: str | None = None,
) -> dict[str, Any] | None:
    if not isinstance(raw, dict):
        return None

    institution_id = _short_openalex_id(raw.get("id"))
    name = raw.get("display_name") or raw.get("name")
    name_text = str(name).strip() if name is not None else None

    if not institution_id and not name_text:
        return None

    country = raw.get("country_code")
    inst_type = raw.get("type")

    result: dict[str, Any] = {
        "id": institution_id,
        "name": name_text or None,
        "country_code": str(country).strip() if country else None,
        "type": str(inst_type).strip() if inst_type else None,
    }
    if relationship is not None:
        result["relationship"] = relationship
    return result


def _affiliation_is_current(affiliation: dict[str, Any], current_year: int) -> bool:
    if affiliation.get("is_current") is True:
        return True
    if str(affiliation.get("relationship", "")).lower() == "current":
        return True

    years = affiliation.get("years")
    if isinstance(years, list) and years:
        numeric_years: list[int] = []
        for year in years:
            try:
                numeric_years.append(int(year))
            except (TypeError, ValueError):
                continue
        if numeric_years and max(numeric_years) >= current_year:
            return True
    return False


def _extract_institutions(author: dict[str, Any]) -> list[dict[str, Any]]:
    current_year = datetime.now(UTC).year
    selected: list[dict[str, Any]] = []
    seen_ids: set[str] = set()

    def add_institution(raw: dict[str, Any] | None) -> None:
        if len(selected) >= MAX_INSTITUTIONS:
            return
        normalized = _institution_from_raw(raw, relationship="current")
        if normalized is None:
            return
        institution_id = normalized.get("id")
        if institution_id:
            if institution_id in seen_ids:
                return
            seen_ids.add(institution_id)
        selected.append(normalized)

    affiliations = author.get("affiliations")
    if isinstance(affiliations, list):
        for affiliation in affiliations:
            if not isinstance(affiliation, dict):
                continue
            if not _affiliation_is_current(affiliation, current_year):
                continue
            institution = affiliation.get("institution")
            if isinstance(institution, dict):
                add_institution(institution)
            else:
                add_institution(affiliation)

    if not selected:
        last_known = author.get("last_known_institutions")
        if isinstance(last_known, list):
            for institution in last_known:
                if isinstance(institution, dict):
                    add_institution(institution)

    return selected


def _extract_topics(author: dict[str, Any]) -> list[dict[str, Any]]:
    topics_raw = author.get("topics")
    if not isinstance(topics_raw, list):
        return []

    topics: list[dict[str, Any]] = []
    for item in topics_raw[:MAX_TOPICS]:
        if not isinstance(item, dict):
            continue
        topic_id = _short_openalex_id(item.get("id"))
        name = item.get("display_name") or item.get("name")
        name_text = str(name).strip() if name is not None else None
        score = item.get("score")
        try:
            score_value = float(score) if score is not None else None
        except (TypeError, ValueError):
            score_value = None

        if not topic_id and not name_text:
            continue

        topics.append(
            {
                "id": topic_id,
                "name": name_text,
                "score": score_value,
            }
        )
    return topics


def normalize_openalex_author(author: dict[str, Any]) -> dict[str, Any] | None:
    """Normalize one OpenAlex author into the researcher candidate shape."""
    openalex_id = _short_openalex_id(author.get("id"))
    if not openalex_id:
        return None

    display_name = author.get("display_name")
    if display_name is None or not str(display_name).strip():
        return None

    alternatives_raw = author.get("display_name_alternatives")
    alternative_names: list[str] = []
    if isinstance(alternatives_raw, list):
        for name in alternatives_raw:
            if name is None:
                continue
            text = str(name).strip()
            if text:
                alternative_names.append(text)

    institutions = _extract_institutions(author)
    primary_institution = None
    if institutions:
        first = institutions[0]
        primary_institution = {
            "id": first.get("id"),
            "name": first.get("name"),
            "country_code": first.get("country_code"),
            "type": first.get("type"),
        }

    works_api_url = author.get("works_api_url")
    works_api_url_text = str(works_api_url).strip() if works_api_url else None

    return {
        "candidate_id": f"openalex:{openalex_id}",
        "openalex_id": openalex_id,
        "display_name": str(display_name).strip(),
        "alternative_names": alternative_names,
        "orcid": _normalize_orcid(author.get("orcid")),
        "primary_institution": primary_institution,
        "institutions": institutions,
        "topics": _extract_topics(author),
        "works_count": _as_optional_int(author.get("works_count")),
        "cited_by_count": _as_optional_int(author.get("cited_by_count")),
        "works_api_url": works_api_url_text or None,
        "source": "openalex",
        "details_loaded": True,
    }


def normalize_autocomplete_author(item: dict[str, Any]) -> dict[str, Any] | None:
    openalex_id = _short_openalex_id(item.get("id"))
    if not openalex_id or not is_valid_openalex_author_id(openalex_id):
        return None

    display_name = item.get("display_name")
    if display_name is None or not str(display_name).strip():
        return None

    hint = item.get("hint")
    hint_text = str(hint).strip() if hint is not None and str(hint).strip() else None

    external_id = item.get("external_id")
    orcid = None
    if external_id is not None:
        external_text = str(external_id).strip()
        if "orcid.org" in external_text.lower() or re.fullmatch(
            r"\d{4}-\d{4}-\d{4}-\d{3}[\dX]",
            external_text,
        ):
            orcid = _normalize_orcid(external_text)

    return {
        "candidate_id": f"openalex:{openalex_id}",
        "openalex_id": openalex_id,
        "display_name": str(display_name).strip(),
        "hint": hint_text,
        "orcid": orcid,
        "works_count": _as_optional_int(item.get("works_count")),
        "cited_by_count": _as_optional_int(item.get("cited_by_count")),
        "source": "openalex",
        "details_loaded": False,
    }


async def _openalex_get(url: str, *, params: dict[str, Any]) -> httpx.Response:
    headers = {
        "User-Agent": USER_AGENT,
        "Accept": "application/json",
    }
    try:
        return await provider_get(
            "openalex",
            url,
            params=params,
            timeout=REQUEST_TIMEOUT_SECONDS,
            follow_redirects=True,
            headers=headers,
        )
    except httpx.TimeoutException as exc:
        raise OpenAlexApiError(
            "OpenAlex author search timed out. Please try again shortly."
        ) from exc
    except httpx.HTTPError as exc:
        raise OpenAlexApiError(
            "OpenAlex author search is temporarily unavailable."
        ) from exc


async def autocomplete_openalex_authors(query: str) -> list[dict]:
    """Lightweight OpenAlex autocomplete for typeahead suggestions."""
    normalized_query = normalize_autocomplete_query(query)
    if len(normalized_query) < 3:
        return []

    cached = _autocomplete_cache.get(normalized_query)
    if cached is not None:
        return cached

    api_key = _require_api_key()
    response = await _openalex_get(
        OPENALEX_AUTOCOMPLETE_AUTHORS_URL,
        params={"q": normalized_query, "api_key": api_key},
    )

    if response.status_code >= 500:
        raise OpenAlexApiError(
            "OpenAlex author search is temporarily unavailable."
        )
    if response.status_code >= 400:
        raise OpenAlexApiError(
            "OpenAlex rejected the author autocomplete request.",
            status_code=502,
        )

    try:
        payload = response.json()
    except ValueError as exc:
        raise OpenAlexApiError(
            "OpenAlex returned an invalid response."
        ) from exc

    results = payload.get("results") if isinstance(payload, dict) else None
    if not isinstance(results, list):
        normalized: list[dict] = []
    else:
        normalized = []
        for item in results:
            if not isinstance(item, dict):
                continue
            candidate = normalize_autocomplete_author(item)
            if candidate is not None:
                normalized.append(candidate)
            if len(normalized) >= MAX_AUTOCOMPLETE_RESULTS:
                break

    _autocomplete_cache.set(normalized_query, normalized)
    return normalized


async def fetch_openalex_author_payload(openalex_id: str) -> dict[str, Any]:
    """Retrieve the raw OpenAlex author JSON payload."""
    cleaned_id = (openalex_id or "").strip()
    if cleaned_id.startswith(OPENALEX_ID_PREFIX):
        cleaned_id = cleaned_id[len(OPENALEX_ID_PREFIX) :]
    cleaned_id = cleaned_id.strip()

    if not is_valid_openalex_author_id(cleaned_id):
        raise OpenAlexApiError(
            "Invalid OpenAlex author ID format.",
            status_code=422,
        )

    api_key = _require_api_key()
    response = await _openalex_get(
        f"{OPENALEX_AUTHORS_URL}/{cleaned_id}",
        params={"api_key": api_key},
    )

    if response.status_code == 404:
        raise OpenAlexApiError(
            "Researcher not found in OpenAlex.",
            status_code=404,
        )
    if response.status_code >= 500:
        raise OpenAlexApiError(
            "OpenAlex author lookup is temporarily unavailable."
        )
    if response.status_code >= 400:
        raise OpenAlexApiError(
            "OpenAlex rejected the author lookup request.",
            status_code=502,
        )

    try:
        payload = response.json()
    except ValueError as exc:
        raise OpenAlexApiError(
            "OpenAlex returned an invalid response."
        ) from exc

    if not isinstance(payload, dict):
        raise OpenAlexApiError(
            "OpenAlex returned an invalid author payload."
        )
    return payload


async def get_openalex_author(openalex_id: str) -> dict:
    """Retrieve and normalize a single OpenAlex author by ID."""
    payload = await fetch_openalex_author_payload(openalex_id)
    normalized = normalize_openalex_author(payload)
    if normalized is None:
        raise OpenAlexApiError(
            "OpenAlex returned an incomplete author record."
        )
    return normalized


async def search_openalex_authors(query: str, limit: int = 10) -> list[dict]:
    """
    Full OpenAlex author search (legacy / non-typeahead use).

    Typeahead should use autocomplete_openalex_authors instead.
    """
    cleaned_query = query.strip()
    if not cleaned_query:
        return []

    api_key = _require_api_key()
    per_page = max(1, min(limit, 20))
    response = await _openalex_get(
        OPENALEX_AUTHORS_URL,
        params={
            "search": cleaned_query,
            "per_page": per_page,
            "api_key": api_key,
        },
    )

    if response.status_code >= 500:
        raise OpenAlexApiError(
            "OpenAlex author search is temporarily unavailable."
        )
    if response.status_code >= 400:
        raise OpenAlexApiError(
            "OpenAlex rejected the author search request.",
            status_code=502,
        )

    try:
        payload = response.json()
    except ValueError as exc:
        raise OpenAlexApiError(
            "OpenAlex returned an invalid response."
        ) from exc

    results = payload.get("results") if isinstance(payload, dict) else None
    if not isinstance(results, list):
        return []

    normalized: list[dict] = []
    for author in results:
        if not isinstance(author, dict):
            continue
        candidate = normalize_openalex_author(author)
        if candidate is not None:
            normalized.append(candidate)

    return normalized
