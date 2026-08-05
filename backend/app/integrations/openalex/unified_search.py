"""Unified OpenAlex search for authors, works, and grants-linked publications."""

from __future__ import annotations

from typing import Any

from app.integrations.openalex.client import (
    MAX_TOPICS,
    OpenAlexApiError,
    _as_optional_int,
    _extract_institutions,
    _extract_topics,
    _normalize_orcid,
    _openalex_get,
    _require_api_key,
    _short_openalex_id,
)

OPENALEX_AUTHORS_URL = "https://api.openalex.org/authors"
OPENALEX_WORKS_URL = "https://api.openalex.org/works"
OPENALEX_AWARDS_URL = "https://api.openalex.org/awards"

ENTITY_ENDPOINTS = {
    "authors": OPENALEX_AUTHORS_URL,
    "works": OPENALEX_WORKS_URL,
    "grants": OPENALEX_AWARDS_URL,
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


def _optional_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _extract_authorship_institutions(
    authorship: dict[str, Any],
) -> tuple[list[dict[str, Any]], list[str], list[str]]:
    """Return (institutions, institution_ids, countries) from a work authorship."""
    institutions: list[dict[str, Any]] = []
    institution_ids: list[str] = []
    countries: list[str] = []
    seen_inst: set[str] = set()
    seen_country: set[str] = set()

    raw_institutions = authorship.get("institutions")
    if isinstance(raw_institutions, list):
        for raw in raw_institutions:
            if not isinstance(raw, dict):
                continue
            inst_id = _short_openalex_id(raw.get("id"))
            name = _optional_str(raw.get("display_name") or raw.get("name"))
            country = _optional_str(raw.get("country_code") or raw.get("country"))
            if not inst_id and not name:
                continue
            key = (inst_id or "") + "|" + (name or "").casefold()
            if key in seen_inst:
                continue
            seen_inst.add(key)
            entry = {
                "id": inst_id,
                "name": name,
                "country_code": country,
                "type": _optional_str(raw.get("type")),
            }
            institutions.append(entry)
            if inst_id:
                institution_ids.append(inst_id)
            if country and country.casefold() not in seen_country:
                seen_country.add(country.casefold())
                countries.append(country)

    raw_countries = authorship.get("countries") or authorship.get("countries_distinct_count")
    if isinstance(raw_countries, list):
        for value in raw_countries:
            country = _optional_str(value)
            if country and country.casefold() not in seen_country:
                seen_country.add(country.casefold())
                countries.append(country)

    if not institutions:
        raw_strings = authorship.get("raw_affiliation_strings")
        if isinstance(raw_strings, list):
            for value in raw_strings:
                name = _optional_str(value)
                if not name:
                    continue
                key = name.casefold()
                if key in seen_inst:
                    continue
                seen_inst.add(key)
                institutions.append(
                    {"id": None, "name": name, "country_code": None, "type": None}
                )

    return institutions, institution_ids, countries


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

        institutions, institution_ids, countries = _extract_authorship_institutions(
            authorship
        )
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
                "institutions": institutions,
                "institution_ids": institution_ids,
                "countries": countries,
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

def normalize_search_author(author: dict[str, Any]) -> dict[str, Any] | None:
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

    title = _optional_str(work.get("title")) or _optional_str(work.get("display_name"))
    if not title:
        return None

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
) -> list[dict[str, Any]]:
    normalized: list[dict[str, Any]] = []
    for item in results:
        if not isinstance(item, dict):
            continue
        if entity_type == "authors":
            candidate = normalize_search_author(item)
        elif entity_type == "works":
            candidate = normalize_search_work(item)
        else:
            candidate = normalize_search_grant(item)
        if candidate is not None:
            normalized.append(candidate)
    return normalized


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
        search_works_by_grant_number,
    )

    if source and source != "openalex":
        raise OpenAlexApiError(
            "Only source=openalex is supported in this step.",
            status_code=422,
        )

    if entity_type not in ENTITY_ENDPOINTS:
        raise OpenAlexApiError(
            "entity_type must be one of: authors, works, grants.",
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
        if entity_type == "works":
            return await search_works_by_grant_number(
                query=cleaned_query,
                limit=limit,
                cursor=cursor,
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
            filter_parts.append(f"affiliations.institution.id:{cleaned_institution}")
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
    normalized = _normalize_page(entity_type, results_list)

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
