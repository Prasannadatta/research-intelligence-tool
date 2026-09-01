"""Publication filter helpers for author-analysis results."""

from __future__ import annotations

import re
from typing import Any


_SOURCE_LABELS = {
    "openalex": "OpenAlex",
    "arxiv": "arXiv",
}

_GRANT_NORM_RE = re.compile(r"[^a-z0-9]+")
_VENUE_WHITESPACE_RE = re.compile(r"\s+")

FACET_VENUE_LIMIT = 50
FACET_GRANT_LIMIT = 50
FACET_AUTHOR_LIMIT = 50
FACET_INSTITUTION_LIMIT = 50

_AUTHOR_WHITESPACE_RE = re.compile(r"\s+")
_INSTITUTION_PUNCT_RE = re.compile(r"[^\w\s]+", re.UNICODE)


def normalize_venue_key(value: str | None) -> str | None:
    if value is None:
        return None
    text = _VENUE_WHITESPACE_RE.sub(" ", str(value).strip().lower())
    return text or None


def normalize_grant_number(value: str | None) -> str | None:
    if value is None:
        return None
    text = _GRANT_NORM_RE.sub("", str(value).strip().lower())
    return text or None


def normalize_source_key(value: str | None) -> str | None:
    if value is None:
        return None
    text = str(value).strip().lower()
    if not text:
        return None
    if text in {"oa", "open alex"}:
        return "openalex"
    return text


def source_label(value: str) -> str:
    return _SOURCE_LABELS.get(value, value.replace("_", " ").title())


def publication_year(item: dict[str, Any]) -> int | None:
    for key in ("publication_year", "year"):
        raw = item.get(key)
        if raw is None or raw == "":
            continue
        try:
            year = int(raw)
        except (TypeError, ValueError):
            continue
        if 1000 <= year <= 2100:
            return year

    for key in ("publication_date", "published_date"):
        raw = item.get(key)
        if raw is None or raw == "":
            continue
        text = str(raw).strip()
        if len(text) >= 4 and text[:4].isdigit():
            year = int(text[:4])
            if 1000 <= year <= 2100:
                return year
    return None


def publication_sources(item: dict[str, Any]) -> list[str]:
    sources: list[str] = []
    for raw in item.get("providers") or []:
        key = normalize_source_key(raw)
        if key and key not in sources:
            sources.append(key)
    source = normalize_source_key(item.get("source"))
    if source and source not in sources:
        sources.append(source)
    return sources


def publication_venue(item: dict[str, Any]) -> str | None:
    for key in ("journal", "primary_source", "venue", "source_name"):
        value = item.get(key)
        if value is None:
            continue
        text = " ".join(str(value).split())
        if text:
            return text
    return None


def normalize_institution_name(value: str | None) -> str | None:
    if value is None:
        return None
    text = _INSTITUTION_PUNCT_RE.sub(" ", str(value).strip().lower())
    text = _VENUE_WHITESPACE_RE.sub(" ", text).strip()
    return text or None


def institution_key(*, provider_id: Any = None, name: Any = None, country: Any = None) -> str | None:
    provider_text = " ".join(str(provider_id or "").split()).strip()
    if provider_text:
        return f"institution:{provider_text.lower()}"
    name_key = normalize_institution_name(str(name)) if name is not None else None
    if not name_key:
        return None
    country_key = " ".join(str(country or "").split()).strip().lower()
    return f"name:{name_key}|country:{country_key}"


def publication_institutions(item: dict[str, Any]) -> list[dict[str, Any]]:
    institutions: list[dict[str, Any]] = []
    seen: set[str] = set()
    raw_authors = item.get("authors")
    if not isinstance(raw_authors, list):
        return institutions

    for author in raw_authors:
        if not isinstance(author, dict):
            continue
        author_countries = author.get("countries") if isinstance(author.get("countries"), list) else []
        raw_institutions = author.get("institutions")
        if not isinstance(raw_institutions, list):
            continue
        raw_ids = author.get("institution_ids") if isinstance(author.get("institution_ids"), list) else []
        for index, raw in enumerate(raw_institutions):
            if isinstance(raw, dict):
                provider_id = raw.get("id") or raw.get("institution_id") or raw.get("openalex_id")
                name = raw.get("name") or raw.get("display_name") or raw.get("institution_name")
                country = raw.get("country_code") or raw.get("country")
            else:
                provider_id = raw_ids[index] if index < len(raw_ids) else None
                name = raw
                country = author_countries[index] if index < len(author_countries) else None
            key = institution_key(provider_id=provider_id, name=name, country=country)
            label = " ".join(str(name or provider_id or "").split()).strip()
            if not key or not label or key in seen:
                continue
            seen.add(key)
            institutions.append(
                {
                    "value": key,
                    "label": label,
                    "country": " ".join(str(country or "").split()).strip() or None,
                    "provider_id": " ".join(str(provider_id or "").split()).strip() or None,
                }
            )
    return institutions


def publication_grants(item: dict[str, Any]) -> list[dict[str, str | None]]:
    grants: list[dict[str, str | None]] = []
    seen: set[str] = set()
    raw_grants = item.get("grants")
    if not isinstance(raw_grants, list):
        return grants
    for row in raw_grants:
        if not isinstance(row, dict):
            continue
        award_id = (
            row.get("award_id")
            or row.get("funder_award_id")
            or row.get("grant_number")
        )
        if award_id is None:
            continue
        display = " ".join(str(award_id).split())
        if not display:
            continue
        key = normalize_grant_number(display)
        if not key or key in seen:
            continue
        seen.add(key)
        funder = row.get("funder_name") or row.get("funder")
        grants.append(
            {
                "grant_number": display,
                "normalized": key,
                "funder": " ".join(str(funder).split()) if funder else None,
            }
        )
    matched = item.get("matched_grant_number")
    if matched:
        display = " ".join(str(matched).split())
        key = normalize_grant_number(display)
        if key and key not in seen:
            grants.append(
                {
                    "grant_number": display,
                    "normalized": key,
                    "funder": None,
                }
            )
    return grants


def normalize_author_key(value: str | None) -> str | None:
    if value is None:
        return None
    text = _AUTHOR_WHITESPACE_RE.sub(" ", str(value).strip().lower())
    return text or None


def publication_authors(item: dict[str, Any]) -> list[dict[str, Any]]:
    """Extract author facet keys from a work item."""
    authors: list[dict[str, Any]] = []
    seen: set[str] = set()
    raw_authors = item.get("authors")
    if not isinstance(raw_authors, list):
        return authors

    for row in raw_authors:
        if not isinstance(row, dict):
            continue
        name = " ".join(
            str(row.get("display_name") or row.get("name") or "").split()
        )
        canonical = row.get("canonical_author_id")
        if canonical is not None:
            canonical = str(canonical).strip() or None

        provider_ids = row.get("provider_ids") if isinstance(row.get("provider_ids"), dict) else {}
        openalex_ids = []
        for value in provider_ids.get("openalex") or []:
            text = str(value).strip()
            if text and text not in openalex_ids:
                openalex_ids.append(text)
        raw_id = row.get("id") or row.get("openalex_id")
        if raw_id:
            text = str(raw_id).strip()
            if text.upper().startswith("A") and text not in openalex_ids:
                openalex_ids.append(text)

        # Prefer stable IDs for filter matching; fall back to normalized name.
        value = None
        if canonical:
            value = f"canonical:{canonical}"
        elif openalex_ids:
            value = f"openalex:{openalex_ids[0]}"
        else:
            name_key = normalize_author_key(name)
            if name_key:
                value = f"name:{name_key}"
        if not value or value in seen:
            continue
        seen.add(value)
        authors.append(
            {
                "value": value,
                "label": name or value,
                "canonical_author_id": canonical,
                "openalex_ids": openalex_ids,
                "name_key": normalize_author_key(name),
            }
        )
    return authors


def normalize_filters(raw: dict[str, Any] | None) -> dict[str, Any]:
    raw = raw or {}
    from_year = raw.get("from_year")
    to_year = raw.get("to_year")
    try:
        from_year_int = int(from_year) if from_year is not None else None
    except (TypeError, ValueError):
        from_year_int = None
    try:
        to_year_int = int(to_year) if to_year is not None else None
    except (TypeError, ValueError):
        to_year_int = None

    if from_year_int is not None and to_year_int is not None and from_year_int > to_year_int:
        from_year_int, to_year_int = to_year_int, from_year_int

    sources = []
    for value in raw.get("sources") or []:
        key = normalize_source_key(value)
        if key and key not in sources:
            sources.append(key)

    venues = []
    venue_keys: set[str] = set()
    for value in raw.get("venues") or []:
        key = normalize_venue_key(value)
        if key and key not in venue_keys:
            venue_keys.add(key)
            venues.append(key)

    institutions = []
    institution_keys: set[str] = set()
    for value in raw.get("institutions") or []:
        text = " ".join(str(value or "").split()).strip()
        if not text:
            continue
        key = text if ":" in text else institution_key(name=text)
        if key and key not in institution_keys:
            institution_keys.add(key)
            institutions.append(key)

    grant_numbers = []
    grant_keys: set[str] = set()
    for value in raw.get("grant_numbers") or []:
        key = normalize_grant_number(value)
        if key and key not in grant_keys:
            grant_keys.add(key)
            grant_numbers.append(key)

    authors = []
    author_keys: set[str] = set()
    for value in raw.get("authors") or []:
        text = " ".join(str(value or "").split())
        if not text:
            continue
        key = text.lower() if ":" in text else f"name:{normalize_author_key(text)}"
        if key and key not in author_keys:
            author_keys.add(key)
            authors.append(key)

    return {
        "from_year": from_year_int,
        "to_year": to_year_int,
        "sources": sources,
        "institutions": institutions,
        "venues": venues,
        "grant_numbers": grant_numbers,
        "authors": authors,
    }


def filters_key(filters: dict[str, Any] | None) -> str:
    normalized = normalize_filters(filters)
    parts = [
        f"from:{normalized['from_year'] or ''}",
        f"to:{normalized['to_year'] or ''}",
        "sources:" + ",".join(normalized["sources"]),
        "institutions:" + ",".join(sorted(normalized["institutions"])),
        "venues:" + ",".join(sorted(normalized["venues"])),
        "grants:" + ",".join(sorted(normalized["grant_numbers"])),
        "authors:" + ",".join(sorted(normalized["authors"])),
    ]
    return "|".join(parts)


def filters_key_matches(cursor_key: Any, active_key: str) -> bool:
    cursor_text = str(cursor_key or "")
    if cursor_text == active_key:
        return True
    # Older pagination cursors predate the institution facet segment.
    legacy_active_key = active_key.replace("|institutions:", "")
    return cursor_text == legacy_active_key


def item_matches_filters(item: dict[str, Any], filters: dict[str, Any] | None) -> bool:
    normalized = normalize_filters(filters)
    year = publication_year(item)

    if normalized["from_year"] is not None:
        if year is None or year < normalized["from_year"]:
            return False
    if normalized["to_year"] is not None:
        if year is None or year > normalized["to_year"]:
            return False

    if normalized["sources"]:
        item_sources = set(publication_sources(item))
        if not item_sources.intersection(normalized["sources"]):
            return False

    if normalized["venues"]:
        venue_key = normalize_venue_key(publication_venue(item))
        if venue_key not in normalized["venues"]:
            return False

    if normalized["institutions"]:
        item_institution_keys = {
            row["value"]
            for row in publication_institutions(item)
            if row.get("value")
        }
        if not item_institution_keys.intersection(normalized["institutions"]):
            return False

    if normalized["grant_numbers"]:
        grant_keys = {row["normalized"] for row in publication_grants(item) if row.get("normalized")}
        if not grant_keys.intersection(normalized["grant_numbers"]):
            return False

    if normalized["authors"]:
        item_author_keys = {row["value"] for row in publication_authors(item) if row.get("value")}
        # Also accept bare name matches against name:* keys.
        for author in publication_authors(item):
            name_key = author.get("name_key")
            if name_key:
                item_author_keys.add(f"name:{name_key}")
        if not item_author_keys.intersection(set(normalized["authors"])):
            return False

    return True


def apply_publication_filters(
    items: list[dict[str, Any]],
    filters: dict[str, Any] | None,
) -> list[dict[str, Any]]:
    normalized = normalize_filters(filters)
    if not any(
        [
            normalized["from_year"] is not None,
            normalized["to_year"] is not None,
            normalized["sources"],
            normalized["institutions"],
            normalized["venues"],
            normalized["grant_numbers"],
            normalized["authors"],
        ]
    ):
        return list(items)
    return [item for item in items if item_matches_filters(item, normalized)]


def build_publication_facets(
    items: list[dict[str, Any]],
    *,
    venue_limit: int = FACET_VENUE_LIMIT,
    grant_limit: int = FACET_GRANT_LIMIT,
    author_limit: int = FACET_AUTHOR_LIMIT,
    institution_limit: int = FACET_INSTITUTION_LIMIT,
) -> dict[str, Any]:
    source_counts: dict[str, int] = {}
    institution_counts: dict[str, dict[str, Any]] = {}
    venue_counts: dict[str, dict[str, Any]] = {}
    grant_counts: dict[str, dict[str, Any]] = {}
    author_counts: dict[str, dict[str, Any]] = {}

    for item in items:
        for source in publication_sources(item):
            source_counts[source] = source_counts.get(source, 0) + 1

        for institution in publication_institutions(item):
            key = institution.get("value")
            if not key:
                continue
            bucket = institution_counts.get(key)
            if bucket is None:
                institution_counts[key] = {
                    "value": key,
                    "label": institution.get("label") or key,
                    "country": institution.get("country"),
                    "count": 1,
                }
            else:
                bucket["count"] += 1
                label = institution.get("label") or ""
                if len(label) > len(str(bucket.get("label") or "")):
                    bucket["label"] = label
                if not bucket.get("country") and institution.get("country"):
                    bucket["country"] = institution["country"]

        venue = publication_venue(item)
        venue_key = normalize_venue_key(venue)
        if venue and venue_key:
            bucket = venue_counts.get(venue_key)
            if bucket is None:
                venue_counts[venue_key] = {"value": venue_key, "label": venue, "count": 1}
            else:
                bucket["count"] += 1
                # Prefer the longer original display name when variants collide.
                if len(venue) > len(str(bucket.get("label") or "")):
                    bucket["label"] = venue

        for grant in publication_grants(item):
            key = grant["normalized"]
            if not key:
                continue
            bucket = grant_counts.get(key)
            if bucket is None:
                grant_counts[key] = {
                    "grant_number": grant["grant_number"],
                    "funder": grant.get("funder"),
                    "publication_count": 1,
                    "_key": key,
                }
            else:
                bucket["publication_count"] += 1
                if not bucket.get("funder") and grant.get("funder"):
                    bucket["funder"] = grant["funder"]

        for author in publication_authors(item):
            key = author.get("value")
            if not key:
                continue
            bucket = author_counts.get(key)
            if bucket is None:
                author_counts[key] = {
                    "value": key,
                    "label": author.get("label") or key,
                    "count": 1,
                    "canonical_author_id": author.get("canonical_author_id"),
                }
            else:
                bucket["count"] += 1
                label = author.get("label") or ""
                if len(label) > len(str(bucket.get("label") or "")):
                    bucket["label"] = label
                if not bucket.get("canonical_author_id") and author.get("canonical_author_id"):
                    bucket["canonical_author_id"] = author["canonical_author_id"]

    sources = [
        {
            "value": key,
            "label": source_label(key),
            "count": count,
        }
        for key, count in sorted(
            source_counts.items(),
            key=lambda row: (-row[1], row[0]),
        )
    ]

    venues = sorted(
        venue_counts.values(),
        key=lambda row: (-int(row["count"]), str(row["label"]).lower()),
    )[: max(1, venue_limit)]

    grants = sorted(
        (
            {
                "grant_number": row["grant_number"],
                "funder": row.get("funder"),
                "publication_count": row["publication_count"],
            }
            for row in grant_counts.values()
        ),
        key=lambda row: (-int(row["publication_count"]), str(row["grant_number"]).lower()),
    )[: max(1, grant_limit)]

    authors = sorted(
        author_counts.values(),
        key=lambda row: (-int(row["count"]), str(row["label"]).lower()),
    )[: max(1, author_limit)]

    institutions = sorted(
        institution_counts.values(),
        key=lambda row: (-int(row["count"]), str(row["label"]).lower()),
    )[: max(1, institution_limit)]

    return {
        "sources": sources,
        "institutions": institutions,
        "venues": venues,
        "grants": grants,
        "authors": authors,
    }


def filters_without_facet(filters: dict[str, Any] | None, facet: str) -> dict[str, Any]:
    normalized = normalize_filters(filters)
    if facet == "sources":
        normalized["sources"] = []
    elif facet == "institutions":
        normalized["institutions"] = []
    elif facet == "venues":
        normalized["venues"] = []
    elif facet == "grants":
        normalized["grant_numbers"] = []
    elif facet == "authors":
        normalized["authors"] = []
    return normalized


def build_dependent_publication_facets(
    items: list[dict[str, Any]],
    filters: dict[str, Any] | None,
    *,
    venue_limit: int = FACET_VENUE_LIMIT,
    grant_limit: int = FACET_GRANT_LIMIT,
    author_limit: int = FACET_AUTHOR_LIMIT,
    institution_limit: int = FACET_INSTITUTION_LIMIT,
) -> dict[str, Any]:
    source_facets = build_publication_facets(
        apply_publication_filters(items, filters_without_facet(filters, "sources")),
        venue_limit=1,
        grant_limit=1,
        author_limit=1,
        institution_limit=1,
    )["sources"]
    institution_facets = build_publication_facets(
        apply_publication_filters(items, filters_without_facet(filters, "institutions")),
        venue_limit=1,
        grant_limit=1,
        author_limit=1,
        institution_limit=institution_limit,
    )["institutions"]
    venue_facets = build_publication_facets(
        apply_publication_filters(items, filters_without_facet(filters, "venues")),
        venue_limit=venue_limit,
        grant_limit=1,
        author_limit=1,
        institution_limit=1,
    )["venues"]
    grant_facets = build_publication_facets(
        apply_publication_filters(items, filters_without_facet(filters, "grants")),
        venue_limit=1,
        grant_limit=grant_limit,
        author_limit=1,
        institution_limit=1,
    )["grants"]
    author_facets = build_publication_facets(
        apply_publication_filters(items, filters_without_facet(filters, "authors")),
        venue_limit=1,
        grant_limit=1,
        author_limit=author_limit,
        institution_limit=1,
    )["authors"]
    return {
        "sources": source_facets,
        "institutions": institution_facets,
        "venues": venue_facets,
        "grants": grant_facets,
        "authors": author_facets,
    }


def search_venue_facets(
    items: list[dict[str, Any]],
    query: str,
    *,
    limit: int = 20,
) -> list[dict[str, Any]]:
    facets = build_publication_facets(items, venue_limit=10_000, grant_limit=1, institution_limit=1)
    needle = normalize_venue_key(query) or ""
    if not needle:
        return facets["venues"][:limit]
    matches = []
    for row in facets["venues"]:
        value = str(row.get("value") or "")
        label_key = normalize_venue_key(row.get("label")) or ""
        if needle in value or needle in label_key:
            matches.append(row)
    return matches[:limit]


def search_grant_facets(
    items: list[dict[str, Any]],
    query: str,
    *,
    limit: int = 20,
) -> list[dict[str, Any]]:
    facets = build_publication_facets(items, venue_limit=1, grant_limit=10_000, author_limit=1, institution_limit=1)
    needle = normalize_grant_number(query) or ""
    query_lower = " ".join(str(query or "").split()).lower()
    if not needle and not query_lower:
        return facets["grants"][:limit]
    matches = []
    for row in facets["grants"]:
        grant_key = normalize_grant_number(row.get("grant_number")) or ""
        funder = " ".join(str(row.get("funder") or "").split()).lower()
        if (needle and needle in grant_key) or (query_lower and query_lower in funder):
            matches.append(row)
    return matches[:limit]


def search_author_facets(
    items: list[dict[str, Any]],
    query: str,
    *,
    limit: int = 20,
) -> list[dict[str, Any]]:
    facets = build_publication_facets(
        items,
        venue_limit=1,
        grant_limit=1,
        author_limit=10_000,
        institution_limit=1,
    )
    needle = normalize_author_key(query) or ""
    if not needle:
        return facets["authors"][:limit]
    matches = []
    for row in facets["authors"]:
        label_key = normalize_author_key(row.get("label")) or ""
        value = str(row.get("value") or "").lower()
        if needle in label_key or needle in value:
            matches.append(row)
    return matches[:limit]
