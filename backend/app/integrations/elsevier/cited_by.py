"""Parse Scopus Abstract Retrieval META and Search REF() cited-by payloads.

Do not call Citation Overview or Citation Count APIs from this module.
Scopus Search REF queries must omit the field= parameter.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

import httpx

from app.integrations.elsevier.client import ElsevierApiError, ElsevierClient
from app.services.work_persistence.normalization import normalize_doi

_SCOPUS_ID_RE = re.compile(r"(?:SCOPUS_ID:|2-s2\.0-)(\d+)", re.IGNORECASE)
_YEAR_RE = re.compile(r"^(\d{4})")


@dataclass(frozen=True)
class ScopusWorkIds:
    scopus_id: str | None = None
    eid: str | None = None
    citedby_count: int | None = None


@dataclass
class CitingWorkRecord:
    scopus_id: str | None = None
    eid: str | None = None
    doi: str | None = None
    normalized_doi: str | None = None
    title: str | None = None
    cover_date: str | None = None
    publication_year: int | None = None
    source_title: str | None = None
    affiliations: list[dict[str, str | None]] = field(default_factory=list)


@dataclass
class ScopusSearchPage:
    total_results: int = 0
    start_index: int = 0
    items_per_page: int = 0
    entries: list[CitingWorkRecord] = field(default_factory=list)


def _as_dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _as_list(value: Any) -> list[Any]:
    if value is None:
        return []
    if isinstance(value, list):
        return value
    return [value]


def _text(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, dict):
        for key in ("$", "#text", "_", "value"):
            if key in value:
                return _text(value.get(key))
        return None
    text = str(value).strip()
    return text or None


def _as_int(value: Any) -> int | None:
    text = _text(value)
    if text is None:
        return None
    try:
        return int(float(text))
    except (TypeError, ValueError):
        return None


def extract_numeric_scopus_id(*values: Any) -> str | None:
    for value in values:
        for item in _as_list(value):
            text = _text(item)
            if not text:
                continue
            match = _SCOPUS_ID_RE.search(text)
            if match:
                return match.group(1)
            if text.isdigit():
                return text
    return None


def eid_from_numeric(scopus_id: str | None) -> str | None:
    if not scopus_id:
        return None
    digits = extract_numeric_scopus_id(scopus_id)
    if not digits:
        return None
    return f"2-s2.0-{digits}"


def publication_year_from_cover_date(cover_date: str | None) -> int | None:
    text = _text(cover_date)
    if not text:
        return None
    match = _YEAR_RE.match(text)
    if not match:
        return None
    year = int(match.group(1))
    if 1000 <= year <= 3000:
        return year
    return None


def normalize_affiliations(raw: Any) -> list[dict[str, str | None]]:
    """Dedupe affiliation name+country pairs from a Scopus Search entry."""
    seen: set[tuple[str, str]] = set()
    out: list[dict[str, str | None]] = []
    for item in _as_list(raw):
        payload = _as_dict(item)
        name = _text(payload.get("affilname") or payload.get("affiliation-name"))
        country = _text(
            payload.get("affiliation-country")
            or payload.get("affiliation_country")
            or payload.get("country")
        )
        key = ((name or "").casefold(), (country or "").casefold())
        if key == ("", ""):
            continue
        if key in seen:
            continue
        seen.add(key)
        out.append({"name": name, "country": country})
    return out


def parse_scopus_ids_from_abstract(payload: dict[str, Any] | None) -> ScopusWorkIds:
    root = _as_dict(payload).get("abstracts-retrieval-response") or payload
    core = _as_dict(_as_dict(root).get("coredata"))
    identifier = core.get("dc:identifier") or core.get("dc:identifier")
    eid = _text(core.get("eid"))
    scopus_id = extract_numeric_scopus_id(identifier, eid, core.get("dc:identifier"))
    if not eid and scopus_id:
        eid = eid_from_numeric(scopus_id)
    count = _as_int(core.get("citedby-count"))
    return ScopusWorkIds(scopus_id=scopus_id, eid=eid, citedby_count=count)


def parse_scopus_ids_from_search_entry(entry: dict[str, Any] | None) -> ScopusWorkIds:
    payload = _as_dict(entry)
    identifier = payload.get("dc:identifier")
    eid = _text(payload.get("eid"))
    scopus_id = extract_numeric_scopus_id(identifier, eid)
    if not eid and scopus_id:
        eid = eid_from_numeric(scopus_id)
    return ScopusWorkIds(scopus_id=scopus_id, eid=eid)


def parse_citing_entry(entry: dict[str, Any] | None) -> CitingWorkRecord | None:
    payload = _as_dict(entry)
    if not payload or payload.get("error"):
        return None
    ids = parse_scopus_ids_from_search_entry(payload)
    doi_raw = _text(payload.get("prism:doi") or payload.get("prism:doi"))
    cover = _text(payload.get("prism:coverDate") or payload.get("prism:coverDisplayDate"))
    title = _text(payload.get("dc:title"))
    source = _text(payload.get("prism:publicationName"))
    if not ids.scopus_id and not ids.eid and not doi_raw and not title:
        return None
    return CitingWorkRecord(
        scopus_id=ids.scopus_id,
        eid=ids.eid,
        doi=doi_raw,
        normalized_doi=normalize_doi(doi_raw),
        title=title,
        cover_date=cover,
        publication_year=publication_year_from_cover_date(cover)
        or _as_int(payload.get("prism:coverDisplayDate")),
        source_title=source,
        affiliations=normalize_affiliations(payload.get("affiliation")),
    )


def parse_search_page(payload: dict[str, Any] | None) -> ScopusSearchPage:
    root = _as_dict(_as_dict(payload).get("search-results") or payload)
    entries: list[CitingWorkRecord] = []
    for item in _as_list(root.get("entry")):
        parsed = parse_citing_entry(_as_dict(item))
        if parsed is not None:
            entries.append(parsed)
    return ScopusSearchPage(
        total_results=_as_int(root.get("opensearch:totalResults")) or 0,
        start_index=_as_int(root.get("opensearch:startIndex")) or 0,
        items_per_page=_as_int(root.get("opensearch:itemsPerPage")) or len(entries),
        entries=entries,
    )


def citing_work_dedupe_key(record: CitingWorkRecord) -> str | None:
    if record.scopus_id:
        return f"scopus:{record.scopus_id}"
    if record.eid:
        numeric = extract_numeric_scopus_id(record.eid)
        if numeric:
            return f"scopus:{numeric}"
        return f"eid:{record.eid.casefold()}"
    if record.normalized_doi:
        return f"doi:{record.normalized_doi}"
    return None


def doi_search_query(doi: str) -> str:
    cleaned = normalize_doi(doi) or str(doi).strip()
    return f"DOI({cleaned})"


def ref_query(scopus_id: str) -> str:
    numeric = extract_numeric_scopus_id(scopus_id)
    if not numeric:
        raise ElsevierApiError("Numeric Scopus ID is required for REF queries.", status_code=400)
    return f"REF({numeric})"


async def resolve_scopus_ids_for_doi(
    doi: str,
    *,
    client: ElsevierClient | None = None,
) -> tuple[ScopusWorkIds, str]:
    """META Abstract Retrieval first; fall back to Scopus DOI search. Never uses Citation Overview."""
    client = client or ElsevierClient()
    cleaned = normalize_doi(doi) or str(doi).strip()
    if not cleaned:
        return ScopusWorkIds(), "not_found"

    meta_response = await client.get_abstract_doi(cleaned, view="META")
    if meta_response.status_code == 200:
        ids = parse_scopus_ids_from_abstract(meta_response.json())
        if ids.scopus_id or ids.eid:
            return ids, "meta"
    elif meta_response.status_code in {401, 403}:
        raise ElsevierApiError(
            f"Elsevier Abstract Retrieval denied ({meta_response.status_code}).",
            status_code=meta_response.status_code,
            entitlement=True,
        )
    elif meta_response.status_code not in {404}:
        if meta_response.status_code >= 500 or meta_response.status_code == 429:
            raise ElsevierApiError(
                f"Elsevier Abstract Retrieval failed ({meta_response.status_code}).",
                status_code=meta_response.status_code,
                retryable=True,
            )

    search_response = await client.search_scopus(doi_search_query(cleaned), start=0, count=1)
    if search_response.status_code == 200:
        page = parse_search_page(search_response.json())
        if page.entries:
            first = page.entries[0]
            return (
                ScopusWorkIds(scopus_id=first.scopus_id, eid=first.eid),
                "doi_search",
            )
        return ScopusWorkIds(), "not_found"
    if search_response.status_code in {401, 403}:
        raise ElsevierApiError(
            f"Elsevier Scopus Search denied ({search_response.status_code}).",
            status_code=search_response.status_code,
            entitlement=True,
        )
    if search_response.status_code == 404:
        return ScopusWorkIds(), "not_found"
    raise ElsevierApiError(
        f"Elsevier Scopus Search failed ({search_response.status_code}).",
        status_code=search_response.status_code,
        retryable=search_response.status_code == 429 or search_response.status_code >= 500,
    )


async def fetch_citing_page(
    scopus_id: str,
    *,
    start: int = 0,
    count: int = 25,
    client: ElsevierClient | None = None,
) -> tuple[httpx.Response, ScopusSearchPage]:
    client = client or ElsevierClient()
    response = await client.search_scopus(ref_query(scopus_id), start=start, count=count)
    if response.status_code != 200:
        return response, ScopusSearchPage()
    return response, parse_search_page(response.json())
