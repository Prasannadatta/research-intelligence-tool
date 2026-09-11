"""Unified OpenAlex search for authors and grants-linked publications."""

from __future__ import annotations

import re
from typing import Any
from urllib.parse import unquote, urlparse

from app.core.issn import collect_issns, compact_issn, format_issn
from app.integrations.openalex.client import (
    MAX_TOPICS,
    OpenAlexApiError,
    _as_optional_int,
    _extract_institutions,
    _extract_topics,
    _institution_from_raw,
    _normalize_orcid,
    _openalex_get,
    _require_api_key,
    _short_openalex_id,
)
from app.services.work_persistence.affiliations import normalize_affiliation_payload

_LANDING_UUID_SUFFIX_RE = re.compile(
    r"\([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\)$",
    re.IGNORECASE,
)

OPENALEX_AUTHORS_URL = "https://api.openalex.org/authors"
OPENALEX_WORKS_URL = "https://api.openalex.org/works"
OPENALEX_AWARDS_URL = "https://api.openalex.org/awards"

ENTITY_ENDPOINTS = {
    "authors": OPENALEX_AUTHORS_URL,
}

DEFAULT_PAGE_SIZE = 20
MAX_PAGE_SIZE = 20
# Soft cap for pathological OpenAlex authorship lists; keep all practical co-authors.
MAX_WORK_AUTHORS = 200


def _optional_str(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _title_from_landing_page_url(url: str | None) -> str | None:
    """Recover a display title from repository landing URLs when OpenAlex title is empty.

    Pure/CURis-style paths encode the title in the final path segment, e.g.
    ``.../one-and-twoaxis-squeezing-...(uuid).html``.
    """
    text = _optional_str(url)
    if not text:
        return None
    path = unquote(urlparse(text).path).rstrip("/")
    if not path:
        return None
    segment = path.rsplit("/", 1)[-1]
    if segment.lower().endswith(".html"):
        segment = segment[: -len(".html")]
    segment = _LANDING_UUID_SUFFIX_RE.sub("", segment).strip("-_. ")
    if len(segment) < 8:
        return None
    # Skip opaque identifiers (OpenAlex/MAG ids, bare UUIDs).
    if re.fullmatch(r"[A-Za-z]?\d{6,}", segment):
        return None
    if re.fullmatch(
        r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}",
        segment,
        flags=re.IGNORECASE,
    ):
        return None
    words = [part for part in re.split(r"[-_]+", segment) if part]
    if len(words) < 2:
        return None
    return " ".join(words)


def _iter_openalex_location_dicts(work: dict[str, Any]) -> list[dict[str, Any]]:
    locations: list[dict[str, Any]] = []
    primary = work.get("primary_location")
    if isinstance(primary, dict):
        locations.append(primary)
    raw_locations = work.get("locations")
    if isinstance(raw_locations, list):
        for location in raw_locations:
            if isinstance(location, dict):
                locations.append(location)
    return locations


def resolve_openalex_work_title(work: dict[str, Any], *, openalex_id: str) -> str:
    """Return a persistable title for an OpenAlex work.

    Empty ``title``/``display_name`` is common on repository duplicates that still
    appear in ``meta.count`` (e.g. Monika Schleier-Smith W3099820453). Dropping
    those IDs permanently fails Analyze completeness (107 reported vs 96 linked).
    Prefer landing-page slug recovery; fall back to a stable Untitled label so the
    W-id still enters the provider→canonical pipeline.
    """
    title = _optional_str(work.get("title")) or _optional_str(work.get("display_name"))
    if title:
        return title
    for location in _iter_openalex_location_dicts(work):
        recovered = _title_from_landing_page_url(
            _optional_str(location.get("landing_page_url"))
        )
        if recovered:
            return recovered
    return f"Untitled work {openalex_id}"


def _optional_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _extract_source_issns(work: dict[str, Any], primary_location: dict[str, Any] | None) -> dict[str, Any]:
    source = None
    if isinstance(primary_location, dict) and isinstance(primary_location.get("source"), dict):
        source = primary_location.get("source")
    host_venue = work.get("host_venue")
    if source is None and isinstance(host_venue, dict):
        source = host_venue
    issn_l = compact_issn((source or {}).get("issn_l")) if isinstance(source, dict) else None
    compact_ids = collect_issns(
        issn_l,
        (source or {}).get("issn") if isinstance(source, dict) else None,
        work.get("issn"),
        work.get("issn_l"),
        work.get("issns"),
    )
    preferred = issn_l or (compact_ids[0] if compact_ids else None)
    return {
        "issn": format_issn(preferred),
        "issn_l": format_issn(issn_l),
        "issns": [format_issn(value) for value in compact_ids if format_issn(value)],
    }


def _extract_authorship_institutions(
    authorship: dict[str, Any],
) -> dict[str, Any]:
    """Return normalized publication-specific affiliation metadata."""
    payload = normalize_affiliation_payload(
        authorship,
        id_normalizer=_short_openalex_id,
    )
    return {
        "institutions": payload.institutions,
        "institution_ids": payload.institution_ids,
        "countries": payload.countries,
        "department": payload.department,
        "raw_affiliation_text": payload.raw_affiliation_text,
        "affiliation_source": payload.affiliation_source,
        "affiliation_confidence": payload.affiliation_confidence,
    }


def extract_normalized_work_authors(work: dict[str, Any]) -> list[dict[str, Any]]:
    """Normalize OpenAlex authorships into export/persistence-ready author rows."""
    authors: list[dict[str, Any]] = []
    authorships = work.get("authorships")
    if not isinstance(authorships, list):
        return authors

    for index, authorship in enumerate(authorships):
        if not isinstance(authorship, dict):
            continue
        author = authorship.get("author")
        if not isinstance(author, dict):
            author = {}
        author_id = _short_openalex_id(author.get("id"))
        name = _optional_str(author.get("display_name")) or _optional_str(
            authorship.get("raw_author_name")
        )
        if not name and not author_id:
            continue

        affiliation = _extract_authorship_institutions(authorship)
        orcid = _normalize_orcid(author.get("orcid") or authorship.get("orcid"))
        position_label = _optional_str(authorship.get("author_position"))
        authors.append(
            {
                "id": author_id,
                "name": name,
                "display_name": name,
                "orcid": orcid,
                "author_position": index,
                "author_position_label": position_label,
                "institutions": affiliation["institutions"],
                "institution_ids": affiliation["institution_ids"],
                "countries": affiliation["countries"],
                "department": affiliation["department"],
                "raw_affiliation_text": affiliation["raw_affiliation_text"],
                "affiliation_source": affiliation["affiliation_source"],
                "affiliation_confidence": affiliation["affiliation_confidence"],
                "is_corresponding": bool(authorship.get("is_corresponding")),
                "provider_ids": {
                    "openalex": [author_id] if author_id else [],
                    "orcid": [orcid] if orcid else [],
                    "arxiv": [],
                },
            }
        )
        if len(authors) >= MAX_WORK_AUTHORS:
            break
    return authors


def _extract_work_topics(work: dict[str, Any]) -> list[str]:
    topics: list[str] = []
    seen: set[str] = set()
    for key in ("topics", "concepts", "keywords"):
        raw = work.get(key)
        if not isinstance(raw, list):
            continue
        for entry in raw:
            if isinstance(entry, dict):
                name = _optional_str(
                    entry.get("display_name") or entry.get("name") or entry.get("keyword")
                )
            else:
                name = _optional_str(entry)
            if not name:
                continue
            folded = name.casefold()
            if folded in seen:
                continue
            seen.add(folded)
            topics.append(name)
            if len(topics) >= MAX_TOPICS:
                return topics
    return topics


def _extract_open_access_urls(work: dict[str, Any]) -> tuple[bool | None, str | None, str | None]:
    is_oa = None
    oa_url = None
    pdf_url = None

    open_access = work.get("open_access")
    if isinstance(open_access, dict):
        if "is_oa" in open_access:
            is_oa = bool(open_access.get("is_oa"))
        oa_url = _optional_str(open_access.get("oa_url"))

    for key in ("best_oa_location", "primary_location"):
        location = work.get(key)
        if not isinstance(location, dict):
            continue
        pdf_url = pdf_url or _optional_str(location.get("pdf_url"))
        oa_url = oa_url or _optional_str(location.get("landing_page_url"))

    return is_oa, oa_url, pdf_url


def _extract_biblio(work: dict[str, Any]) -> dict[str, str | None]:
    biblio = work.get("biblio") if isinstance(work.get("biblio"), dict) else {}
    primary = (
        work.get("primary_location")
        if isinstance(work.get("primary_location"), dict)
        else {}
    )
    source = primary.get("source") if isinstance(primary.get("source"), dict) else {}
    first = _optional_str(biblio.get("first_page"))
    last = _optional_str(biblio.get("last_page"))
    pages = None
    if first and last:
        pages = f"{first}-{last}"
    elif first or last:
        pages = first or last
    return {
        "publisher": _optional_str(
            work.get("publisher")
            or source.get("host_organization_name")
            or source.get("publisher")
        ),
        "volume": _optional_str(biblio.get("volume")),
        "issue": _optional_str(biblio.get("issue")),
        "pages": pages,
    }

def _find_author_institution(
    author: dict[str, Any],
    institution_id: str,
) -> dict[str, Any] | None:
    """Locate an institution on the raw OpenAlex author (last_known or affiliations)."""
    prefer = _short_openalex_id(institution_id) or (institution_id or "").strip()
    if not prefer:
        return None

    last_known = author.get("last_known_institutions")
    if isinstance(last_known, list):
        for item in last_known:
            if not isinstance(item, dict):
                continue
            normalized = _institution_from_raw(item)
            if normalized and normalized.get("id") == prefer:
                return {
                    "id": normalized.get("id"),
                    "name": normalized.get("name"),
                    "country_code": normalized.get("country_code"),
                    "type": normalized.get("type"),
                }

    affiliations = author.get("affiliations")
    if isinstance(affiliations, list):
        for affiliation in affiliations:
            if not isinstance(affiliation, dict):
                continue
            institution = affiliation.get("institution")
            raw = institution if isinstance(institution, dict) else affiliation
            normalized = _institution_from_raw(raw if isinstance(raw, dict) else None)
            if normalized and normalized.get("id") == prefer:
                return {
                    "id": normalized.get("id"),
                    "name": normalized.get("name"),
                    "country_code": normalized.get("country_code"),
                    "type": normalized.get("type"),
                }
    return None


def normalize_search_author(
    author: dict[str, Any],
    *,
    prefer_institution_id: str | None = None,
) -> dict[str, Any] | None:
    openalex_id = _short_openalex_id(author.get("id"))
    if not openalex_id:
        return None

    display_name = _optional_str(author.get("display_name"))
    if not display_name:
        return None

    alternatives_raw = author.get("display_name_alternatives")
    alternative_names: list[str] = []
    if isinstance(alternatives_raw, list):
        for name in alternatives_raw:
            text = _optional_str(name)
            if text:
                alternative_names.append(text)

    institutions = _extract_institutions(author)
    preferred = None
    if prefer_institution_id:
        preferred = _find_author_institution(author, prefer_institution_id)
        if preferred:
            prefer_id = preferred.get("id")
            institutions = [preferred] + [
                row
                for row in institutions
                if isinstance(row, dict) and row.get("id") != prefer_id
            ]

    primary_institution = None
    if institutions:
        first = institutions[0]
        primary_institution = {
            "id": first.get("id"),
            "name": first.get("name"),
            "country_code": first.get("country_code"),
            "type": first.get("type"),
        }

    topics = _extract_topics(author)[:MAX_TOPICS]

    return {
        "result_id": f"openalex:{openalex_id}",
        "result_type": "author",
        "openalex_id": openalex_id,
        "display_name": display_name,
        "alternative_names": alternative_names,
        "orcid": _normalize_orcid(author.get("orcid")),
        "primary_institution": primary_institution,
        "topics": topics,
        "works_count": _as_optional_int(author.get("works_count")),
        "cited_by_count": _as_optional_int(author.get("cited_by_count")),
        "source": "openalex",
    }


def normalize_search_work(work: dict[str, Any]) -> dict[str, Any] | None:
    openalex_id = _short_openalex_id(work.get("id"))
    if not openalex_id:
        return None

    title = resolve_openalex_work_title(work, openalex_id=openalex_id)

    authors = extract_normalized_work_authors(work)

    primary_source = None
    primary_location = work.get("primary_location")
    if isinstance(primary_location, dict):
        source = primary_location.get("source")
        if isinstance(source, dict):
            primary_source = _optional_str(source.get("display_name"))
        if not primary_source:
            primary_source = _optional_str(primary_location.get("raw_source_name"))

    is_oa, oa_url, pdf_url = _extract_open_access_urls(work)
    biblio = _extract_biblio(work)
    source_issns = _extract_source_issns(work, primary_location if isinstance(primary_location, dict) else None)

    doi = _optional_str(work.get("doi"))
    if doi and doi.startswith("https://doi.org/"):
        doi = doi[len("https://doi.org/") :]

    ids = work.get("ids") if isinstance(work.get("ids"), dict) else {}
    pmid = _optional_str(ids.get("pmid"))
    if pmid and pmid.lower().startswith("pmid:"):
        pmid = pmid.split(":", 1)[1].strip()
    arxiv_id = _optional_str(ids.get("arxiv"))
    if arxiv_id and arxiv_id.lower().startswith("arxiv:"):
        arxiv_id = arxiv_id.split(":", 1)[1].strip()
    if not doi:
        doi = _optional_str(ids.get("doi"))
        if doi and doi.startswith("https://doi.org/"):
            doi = doi[len("https://doi.org/") :]

    grants: list[dict[str, Any]] = []
    seen_grant_keys: set[str] = set()
    raw_awards = work.get("awards")
    if isinstance(raw_awards, list):
        for award in raw_awards:
            if not isinstance(award, dict):
                continue
            award_id = _optional_str(award.get("funder_award_id")) or _optional_str(
                award.get("display_name")
            )
            if not award_id:
                continue
            key = "".join(ch for ch in award_id.casefold() if ch.isalnum())
            if not key or key in seen_grant_keys:
                continue
            seen_grant_keys.add(key)
            funder_name = _optional_str(award.get("funder_display_name"))
            if not funder_name:
                funder = award.get("funder")
                if isinstance(funder, dict):
                    funder_name = _optional_str(funder.get("display_name"))
            grants.append(
                {
                    "award_id": award_id,
                    "grant_number": award_id,
                    "funder_name": funder_name,
                    "funder": funder_name,
                    "provider": "openalex",
                    "verified": True,
                    "match_type": "structured_award_relationship",
                }
            )

    return {
        "result_id": f"openalex:{openalex_id}",
        "result_type": "work",
        "openalex_id": openalex_id,
        "title": title,
        "publication_year": _as_optional_int(work.get("publication_year")),
        "publication_date": _optional_str(work.get("publication_date")),
        "authors": authors,
        "primary_source": primary_source,
        "issn": source_issns.get("issn"),
        "issn_l": source_issns.get("issn_l"),
        "issns": source_issns.get("issns") or [],
        "doi": doi,
        "pmid": pmid,
        "arxiv_id": arxiv_id,
        "work_type": _optional_str(work.get("type")),
        "language": _optional_str(work.get("language")),
        "cited_by_count": _as_optional_int(work.get("cited_by_count")),
        "citation_count": _as_optional_int(work.get("cited_by_count")),
        "is_open_access": is_oa,
        "open_access_url": oa_url,
        "oa_url": oa_url,
        "pdf_url": pdf_url,
        "publisher": biblio.get("publisher"),
        "volume": biblio.get("volume"),
        "issue": biblio.get("issue"),
        "pages": biblio.get("pages"),
        "topics": _extract_work_topics(work),
        "source": "openalex",
        "grants": grants,
    }


def _lead_investigator_name(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, str):
        return _optional_str(value)
    if not isinstance(value, dict):
        return None

    display = _optional_str(value.get("display_name"))
    if display:
        return display

    given = _optional_str(value.get("given_name")) or ""
    family = _optional_str(value.get("family_name")) or ""
    combined = f"{given} {family}".strip()
    return combined or None


def normalize_search_grant(award: dict[str, Any]) -> dict[str, Any] | None:
    openalex_id = _short_openalex_id(award.get("id"))
    if not openalex_id:
        return None

    funder_name = None
    funder = award.get("funder")
    if isinstance(funder, dict):
        funder_name = _optional_str(funder.get("display_name"))

    return {
        "result_id": f"openalex:{openalex_id}",
        "result_type": "grant",
        "openalex_id": openalex_id,
        "display_name": _optional_str(award.get("display_name")),
        "funder_name": funder_name,
        "funder_award_id": _optional_str(award.get("funder_award_id")),
        "funding_type": _optional_str(award.get("funding_type")),
        "amount": _optional_float(award.get("amount")),
        "currency": _optional_str(award.get("currency")),
        "start_year": _as_optional_int(award.get("start_year")),
        "end_year": _as_optional_int(award.get("end_year")),
        "lead_investigator": _lead_investigator_name(award.get("lead_investigator")),
        "funded_outputs_count": _as_optional_int(award.get("funded_outputs_count")),
        "source": "openalex",
    }


def _normalize_page(
    entity_type: str,
    results: list[Any],
    *,
    prefer_institution_id: str | None = None,
) -> list[dict[str, Any]]:
    normalized: list[dict[str, Any]] = []
    for item in results:
        if not isinstance(item, dict):
            continue
        if entity_type != "authors":
            continue
        candidate = normalize_search_author(
            item,
            prefer_institution_id=prefer_institution_id,
        )
        if candidate is not None:
            normalized.append(candidate)
    return normalized


async def search_openalex_authors_by_orcid(
    orcid: str,
    *,
    limit: int = DEFAULT_PAGE_SIZE,
    cursor: str | None = None,
) -> dict[str, Any]:
    """Return OpenAlex author records whose ORCID matches exactly. No name matching."""
    from app.integrations.orcid.normalize import normalize_orcid_id

    normalized = normalize_orcid_id(orcid)
    empty = {
        "query": normalized or (orcid or ""),
        "entity_type": "authors",
        "source": "openalex",
        "search_mode": "orcid",
        "results": [],
        "next_cursor": None,
        "has_more": False,
    }
    if not normalized:
        return empty

    page_size = max(1, min(int(limit or DEFAULT_PAGE_SIZE), MAX_PAGE_SIZE))
    request_cursor = (cursor or "").strip() or "*"
    api_key = _require_api_key()
    params: dict[str, Any] = {
        "filter": f"orcid:{normalized}",
        "per_page": page_size,
        "cursor": request_cursor,
        "api_key": api_key,
    }
    response = await _openalex_get(OPENALEX_AUTHORS_URL, params=params)
    if response.status_code >= 500:
        raise OpenAlexApiError("OpenAlex search is temporarily unavailable.")
    if response.status_code >= 400:
        raise OpenAlexApiError(
            "OpenAlex rejected the search request.",
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
    matched: list[dict[str, Any]] = []
    for item in _normalize_page("authors", results_list):
        if normalize_orcid_id(item.get("orcid")) == normalized:
            matched.append(item)
    meta = payload.get("meta") if isinstance(payload.get("meta"), dict) else {}
    next_cursor = _optional_str(meta.get("next_cursor"))
    has_more = bool(next_cursor) and len(matched) > 0
    return {
        "query": normalized,
        "entity_type": "authors",
        "source": "openalex",
        "search_mode": "orcid",
        "results": matched,
        "next_cursor": next_cursor if has_more else None,
        "has_more": has_more,
    }


async def unified_openalex_search(
    *,
    query: str | None,
    entity_type: str,
    limit: int = DEFAULT_PAGE_SIZE,
    cursor: str | None = None,
    institution_id: str | None = None,
    topic_id: str | None = None,
    search_mode: str = "auto",
    source: str = "openalex",
) -> dict[str, Any]:
    """
    Search OpenAlex authors or works with cursor paging.

    entity_type=grants treats the query as a grant/award number and returns
    linked Works via awards.funder_award_id (not Award objects).

    For authors, institution_id and topic_id map to OpenAlex filter IDs.
    """
    from app.integrations.openalex.filters import (
        is_valid_institution_id,
        is_valid_topic_id,
    )
    from app.integrations.openalex.grant_number import looks_like_grant_number
    from app.integrations.openalex.grant_search import (
        search_authors_by_grant_number,
        search_publications_for_grant_number,
    )

    if source and source != "openalex":
        raise OpenAlexApiError(
            "Only source=openalex is supported in this step.",
            status_code=422,
        )

    if entity_type not in {"authors", "grants"}:
        raise OpenAlexApiError(
            "entity_type must be one of: authors, grants.",
            status_code=422,
        )

    # Grants mode: grant/award number → linked publications (Works), not Award objects.
    if entity_type == "grants":
        return await search_publications_for_grant_number(
            query=query or "",
            limit=limit,
            cursor=cursor,
        )

    mode = (search_mode or "auto").strip().lower()
    if mode not in {"auto", "keywords", "grant_number"}:
        raise OpenAlexApiError(
            "search_mode must be one of: auto, keywords, grant_number.",
            status_code=422,
        )

    cleaned_query = " ".join((query or "").split())
    cleaned_institution = (institution_id or "").strip() or None
    cleaned_topic = (topic_id or "").strip() or None

    if entity_type == "authors":
        from app.integrations.openalex.client import _short_openalex_id
        from app.integrations.orcid.normalize import normalize_orcid_id

        cleaned_institution = _short_openalex_id(cleaned_institution) or cleaned_institution
        cleaned_topic = _short_openalex_id(cleaned_topic) or cleaned_topic

        orcid_query = normalize_orcid_id(cleaned_query)
        if orcid_query:
            return await search_openalex_authors_by_orcid(
                orcid_query,
                limit=limit,
                cursor=cursor,
            )

    if cleaned_institution and not is_valid_institution_id(cleaned_institution):
        raise OpenAlexApiError(
            "Invalid institution_id format. Expected I followed by digits.",
            status_code=422,
        )
    if cleaned_topic and not is_valid_topic_id(cleaned_topic):
        raise OpenAlexApiError(
            "Invalid topic_id format. Expected T followed by digits.",
            status_code=422,
        )

    # Filters are authors-only and apply to keyword/auto keyword paths.
    if entity_type != "authors":
        cleaned_institution = None
        cleaned_topic = None

    use_grant_number = mode == "grant_number" or (
        mode == "auto" and bool(cleaned_query) and looks_like_grant_number(cleaned_query)
    )

    if use_grant_number:
        if len(cleaned_query) < 3:
            raise OpenAlexApiError(
                "Grant-number search requires at least 3 characters.",
                status_code=422,
            )
        return await search_authors_by_grant_number(
            query=cleaned_query,
            limit=limit,
            cursor=cursor,
        )

    has_author_filters = bool(cleaned_institution or cleaned_topic)
    # Institution/topic filters are constraints only; author searches still need a name query.
    if len(cleaned_query) < 3:
        raise OpenAlexApiError(
            "Query must be at least 3 characters after trimming.",
            status_code=422,
        )

    page_size = max(1, min(int(limit or DEFAULT_PAGE_SIZE), MAX_PAGE_SIZE))
    request_cursor = (cursor or "").strip() or "*"

    api_key = _require_api_key()
    params: dict[str, Any] = {
        "per_page": page_size,
        "cursor": request_cursor,
        "api_key": api_key,
    }
    if cleaned_query:
        params["search"] = cleaned_query

    if entity_type == "authors" and has_author_filters:
        filter_parts: list[str] = []
        if cleaned_institution:
            # Match current/last-known institutions (what the UI shows as primary),
            # not historical affiliations.institution rows.
            filter_parts.append(f"last_known_institutions.id:{cleaned_institution}")
        if cleaned_topic:
            filter_parts.append(f"topics.id:{cleaned_topic}")
        params["filter"] = ",".join(filter_parts)

    response = await _openalex_get(ENTITY_ENDPOINTS[entity_type], params=params)

    if response.status_code >= 500:
        raise OpenAlexApiError(
            "OpenAlex search is temporarily unavailable."
        )
    if response.status_code >= 400:
        raise OpenAlexApiError(
            "OpenAlex rejected the search request.",
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
            "OpenAlex returned an invalid response."
        )

    raw_results = payload.get("results")
    results_list = raw_results if isinstance(raw_results, list) else []
    normalized = _normalize_page(
        entity_type,
        results_list,
        prefer_institution_id=cleaned_institution if entity_type == "authors" else None,
    )

    meta = payload.get("meta") if isinstance(payload.get("meta"), dict) else {}
    next_cursor = meta.get("next_cursor")
    next_cursor_text = _optional_str(next_cursor)
    has_more = bool(next_cursor_text) and len(results_list) > 0

    return {
        "query": cleaned_query,
        "entity_type": entity_type,
        "source": "openalex",
        "search_mode": "keywords",
        "results": normalized,
        "next_cursor": next_cursor_text,
        "has_more": has_more,
    }
