"""CSV export for filtered author and grant publication result sets."""

from __future__ import annotations

import csv
import io
import logging
import re
import time
import uuid
from collections.abc import AsyncIterator, Iterable, Iterator, Sequence
from dataclasses import dataclass, field
from datetime import date
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.services.analysis.author_publications import (
    AuthorAnalysisError,
    _collect_author_publications,
)
from app.services.analysis.publication_filters import (
    apply_publication_filters,
    normalize_filters,
)
from app.services.analysis.work_authors import enrich_publication_items_authors
from app.services.grants.publications import (
    GrantPublicationsError,
    _collect_grant_publications,
    _finalize_publication_grants,
    decode_grant_number,
)
from app.services.work_persistence.normalization import normalize_grant_number


logger = logging.getLogger(__name__)

MULTI_VALUE_DELIMITER = " | "
AFFILIATION_DELIMITER = ", "
FORMULA_PREFIXES = ("=", "+", "-", "@")

ESSENTIAL_COLUMNS = (
    "Title",
    "Publication Date",
    "Publication Year",
    "Journal / Venue",
    "Authors",
    "Author Affiliations",
    "Citation Count",
    "Sources",
    "Primary URL",
    "Grant Numbers",
)

COLUMN_CANDIDATES = (
    "Title",
    "Publication Date",
    "Publication Year",
    "Journal / Venue",
    "Publication Type",
    "Publisher",
    "Volume",
    "Issue",
    "Pages",
    "Authors",
    "Author ORCIDs",
    "Author Affiliations",
    "Author Departments",
    "Author Countries",
    "Citation Count",
    "Citations by Provider",
    "DOI",
    "PMID",
    "arXiv ID",
    "arXiv Version",
    "OpenAlex ID",
    "Scopus ID",
    "Primary URL",
    "PDF URL",
    "Open Access Status",
    "Open Access URL",
    "Sources",
    "Grant Numbers",
    "Grant Funders",
    "Grant Agencies",
    "Grant Providers",
    "Research Topics",
    "Searched Grant",
)

CSV_COLUMNS = list(COLUMN_CANDIDATES)

SOURCE_LABELS = {
    "openalex": "OpenAlex",
    "arxiv": "arXiv",
    "scopus": "Scopus",
    "orcid": "ORCID",
    "elsevier": "Scopus",
}

_FILENAME_SAFE_RE = re.compile(r"[^a-z0-9]+")
_UUID_RE = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$",
    re.I,
)
_NULLISH = frozenset({"", "none", "null", "nan", "n/a", "na", "undefined"})


@dataclass
class ExportAuthor:
    name: str = ""
    orcid: str = ""
    affiliations: list[str] = field(default_factory=list)
    departments: list[str] = field(default_factory=list)
    countries: list[str] = field(default_factory=list)
    provider_author_id: str = ""
    canonical_author_id: str = ""
    affiliation_source: str = "missing"
    orcid_source: str = "missing"


@dataclass
class ExportDiagnostics:
    exported_work_count: int = 0
    authorship_count: int = 0
    authors_with_provider_ids: int = 0
    authors_with_affiliations: int = 0
    authors_with_orcid: int = 0
    works_with_citations: int = 0
    works_with_grants: int = 0
    works_with_topics: int = 0
    database_query_count: int = 0
    export_duration_ms: float = 0.0
    affiliation_from_authorship: int = 0
    affiliation_from_canonical_profile: int = 0
    affiliation_missing: int = 0
    orcid_from_authorship: int = 0
    orcid_from_canonical_profile: int = 0
    orcid_missing: int = 0
    citation_from_item: int = 0
    citation_from_provider: int = 0
    citation_missing: int = 0

    def as_log_dict(self) -> dict[str, Any]:
        return {
            "exported_work_count": self.exported_work_count,
            "authorship_count": self.authorship_count,
            "authors_with_provider_ids": self.authors_with_provider_ids,
            "authors_with_affiliations": self.authors_with_affiliations,
            "authors_with_orcid": self.authors_with_orcid,
            "works_with_citations": self.works_with_citations,
            "works_with_grants": self.works_with_grants,
            "works_with_topics": self.works_with_topics,
            "database_query_count": self.database_query_count,
            "export_duration_ms": round(self.export_duration_ms, 1),
            "affiliation_from_authorship": self.affiliation_from_authorship,
            "affiliation_from_canonical_profile": self.affiliation_from_canonical_profile,
            "affiliation_missing": self.affiliation_missing,
            "orcid_from_authorship": self.orcid_from_authorship,
            "orcid_from_canonical_profile": self.orcid_from_canonical_profile,
            "orcid_missing": self.orcid_missing,
            "citation_from_item": self.citation_from_item,
            "citation_from_provider": self.citation_from_provider,
            "citation_missing": self.citation_missing,
        }


def escape_csv_formula(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, float) and value != value:
        return ""
    text = str(value)
    if text.casefold().strip() in _NULLISH:
        return ""
    if text and text[0] in FORMULA_PREFIXES:
        return f"'{text}"
    return text


def clean_cell(value: Any, *, collapse_whitespace: bool = True) -> str:
    if value is None:
        return ""
    if isinstance(value, float) and value != value:
        return ""
    text = str(value)
    if collapse_whitespace:
        text = " ".join(text.split()).strip()
    else:
        text = text.strip()
    if text.casefold() in _NULLISH:
        return ""
    return text


def join_aligned(values: Sequence[Any]) -> str:
    parts = [clean_cell(value) for value in values]
    if not any(parts):
        return ""
    return MULTI_VALUE_DELIMITER.join(parts)


def join_unique(values: Iterable[Any]) -> str:
    parts: list[str] = []
    seen: set[str] = set()
    for value in values:
        text = clean_cell(value)
        if not text:
            continue
        key = text.casefold()
        if key in seen:
            continue
        seen.add(key)
        parts.append(text)
    return MULTI_VALUE_DELIMITER.join(parts)


def sanitize_filename_part(value: str | None, *, fallback: str = "unknown") -> str:
    text = " ".join(str(value or "").split()).strip().casefold()
    cleaned = _FILENAME_SAFE_RE.sub("-", text).strip("-")
    return cleaned or fallback


def _year_range_filename_part(filters: dict[str, Any] | None) -> str | None:
    if not filters:
        return None
    from_year = filters.get("from_year")
    to_year = filters.get("to_year")
    try:
        from_year_int = int(from_year) if from_year is not None else None
    except (TypeError, ValueError):
        from_year_int = None
    try:
        to_year_int = int(to_year) if to_year is not None else None
    except (TypeError, ValueError):
        to_year_int = None
    if from_year_int is not None and to_year_int is not None:
        return f"{from_year_int}-to-{to_year_int}"
    if from_year_int is not None:
        return f"from-{from_year_int}"
    if to_year_int is not None:
        return f"to-{to_year_int}"
    return None


def build_authors_export_filename(
    authors: list[dict[str, Any]],
    *,
    filters: dict[str, Any] | None = None,
    export_date: date | None = None,
) -> str:
    names = [
        sanitize_filename_part(author.get("display_name"), fallback="author")
        for author in authors
    ]
    year_part = _year_range_filename_part(filters)
    day = (export_date or date.today()).isoformat()
    suffix = year_part or day
    if len(names) >= 4:
        return f"common-publications-{len(names)}-authors-{suffix}.csv"
    if len(names) == 1:
        return f"{names[0]}-publications-{suffix}.csv"
    return f"{'-and-'.join(names)}-common-publications-{suffix}.csv"


def build_grant_export_filename(
    grant_number: str,
    *,
    provider: str | None = None,
    filters: dict[str, Any] | None = None,
    export_date: date | None = None,
) -> str:
    compact = re.sub(r"[^A-Za-z0-9._-]+", "", str(grant_number or "").strip())
    grant_part = compact or sanitize_filename_part(grant_number, fallback="grant")
    year_part = _year_range_filename_part(filters)
    day = (export_date or date.today()).isoformat()
    provider_key = clean_cell(provider).casefold()
    provider_part = provider_key if provider_key in SOURCE_LABELS else ""
    if year_part and provider_part:
        return f"grant-{grant_part}-{provider_part}-{year_part}.csv"
    if year_part:
        return f"grant-{grant_part}-{year_part}.csv"
    return f"grant-{grant_part}-publications-{day}.csv"


def _parse_uuid(value: Any) -> uuid.UUID | None:
    text = clean_cell(value)
    if not text or not _UUID_RE.match(text):
        return None
    try:
        return uuid.UUID(text)
    except (TypeError, ValueError):
        return None


def _source_label(value: Any) -> str:
    text = clean_cell(value)
    if not text:
        return ""
    return SOURCE_LABELS.get(text.casefold(), text)


def _unique_names(values: Iterable[Any]) -> list[str]:
    names: list[str] = []
    seen: set[str] = set()
    for value in values:
        text = clean_cell(value)
        if not text:
            continue
        key = text.casefold()
        if key in seen:
            continue
        seen.add(key)
        names.append(text)
    return names


def _institution_names(raw: Any) -> list[str]:
    if not isinstance(raw, list):
        return []
    names: list[str] = []
    for entry in raw:
        if isinstance(entry, dict):
            names.append(clean_cell(entry.get("name") or entry.get("display_name")))
        else:
            names.append(clean_cell(entry))
    return _unique_names(names)


def _department_names(author: dict[str, Any]) -> list[str]:
    names: list[str] = []
    names.append(clean_cell(author.get("department")))
    raw_institutions = author.get("institutions")
    if isinstance(raw_institutions, list):
        for entry in raw_institutions:
            if isinstance(entry, dict):
                names.append(clean_cell(entry.get("department")))
    return _unique_names(names)


def _country_codes(raw: Any, institutions: Any = None) -> list[str]:
    codes: list[str] = []
    if isinstance(raw, list):
        for entry in raw:
            if isinstance(entry, dict):
                codes.append(clean_cell(entry.get("country_code") or entry.get("country")))
            else:
                codes.append(clean_cell(entry))
    if isinstance(institutions, list):
        for entry in institutions:
            if isinstance(entry, dict):
                codes.append(clean_cell(entry.get("country_code") or entry.get("country")))
    return _unique_names(codes)


def _author_openalex_id(author: dict[str, Any]) -> str:
    provider_ids = author.get("provider_ids")
    if isinstance(provider_ids, dict):
        values = provider_ids.get("openalex") or []
        if isinstance(values, list) and values:
            return clean_cell(values[0])
        if values:
            return clean_cell(values)
    raw = author.get("id") or author.get("openalex_id") or author.get("provider_author_id")
    text = clean_cell(raw)
    if text.upper().startswith("A"):
        return text
    return ""


def _author_orcid_direct(author: dict[str, Any]) -> str:
    provider_ids = author.get("provider_ids")
    if isinstance(provider_ids, dict):
        orcids = provider_ids.get("orcid") or []
        if isinstance(orcids, list) and orcids:
            return clean_cell(orcids[0])
        if orcids:
            return clean_cell(orcids)
    return clean_cell(author.get("orcid"))


def _institution_sort_key(row: Any) -> tuple[Any, ...]:
    return (
        0 if getattr(row, "is_current", False) else 1,
        -(
            getattr(row, "valid_to_year", None)
            or getattr(row, "valid_from_year", None)
            or 0
        ),
        getattr(row, "institution_name", None)
        or getattr(row, "display_name", None)
        or "",
    )


def _profile_institutions(rows: list[Any]) -> tuple[list[str], list[str]]:
    ordered = sorted(rows, key=_institution_sort_key)
    names: list[str] = []
    countries: list[str] = []
    seen_name: set[str] = set()
    seen_country: set[str] = set()
    for row in ordered:
        name = clean_cell(
            getattr(row, "institution_name", None) or getattr(row, "display_name", None)
        )
        if name and name.casefold() not in seen_name:
            seen_name.add(name.casefold())
            names.append(name)
        country = clean_cell(getattr(row, "country_code", None))
        if country and country.casefold() not in seen_country:
            seen_country.add(country.casefold())
            countries.append(country)
    return names, countries


def _topic_names(raw: Any) -> list[str]:
    names: list[str] = []
    if isinstance(raw, list):
        for entry in raw:
            if isinstance(entry, dict):
                names.append(
                    clean_cell(
                        entry.get("display_name")
                        or entry.get("name")
                        or entry.get("label")
                    )
                )
            else:
                names.append(clean_cell(entry))
    elif raw:
        names.append(clean_cell(raw))
    return _unique_names(names)


def _display_grant_number(value: Any) -> str:
    """Normalize grant ID formatting noise for export without inventing awards."""
    text = clean_cell(value)
    if not text:
        return ""
    # Unicode dashes / minus signs → ASCII hyphen; collapse whitespace.
    for ch in ("\u2010", "\u2011", "\u2012", "\u2013", "\u2014", "\u2212"):
        text = text.replace(ch, "-")
    text = " ".join(text.split())
    text = text.strip(" .;,")
    # Leading hyphen fragments like "-AC02-…" are truncated agency prefixes.
    while text.startswith("-"):
        text = text[1:].lstrip()
    # Dangling trailing hyphen is formatting noise when the normalized id is unchanged.
    if text.endswith("-"):
        trimmed = text.rstrip("-").rstrip()
        if trimmed and normalize_grant_number(trimmed) == normalize_grant_number(text):
            text = trimmed
    return text


def _grant_is_provider_label(value: str) -> bool:
    key = clean_cell(value).casefold()
    return key in {"openalex", "arxiv", "scopus", "orcid", "elsevier"}


def _prefer_grant_display(current: str, candidate: str) -> str:
    """Prefer the more complete display form when two IDs normalize identically."""
    left = _display_grant_number(current)
    right = _display_grant_number(candidate)
    if not left:
        return right
    if not right:
        return left

    def _score(value: str) -> tuple[int, int, int, int]:
        has_alpha = 1 if any(ch.isalpha() for ch in value) else 0
        has_hyphen = 1 if "-" in value else 0
        has_space = 1 if " " in value else 0
        return (has_alpha, has_hyphen, -has_space, len(value))

    return right if _score(right) > _score(left) else left


def _dedupe_grants(grants: Sequence[dict[str, Any]]) -> list[dict[str, Any]]:
    """Source-aware grant dedupe for export.

    - Same provider + identical normalized award id → one row (formatting noise).
    - Different providers keep separate rows even for the same award text.
    - Uncertain / non-matching fragments stay separate (no speculative merges).
    """
    merged: dict[str, dict[str, Any]] = {}
    order: list[str] = []
    for grant in grants:
        if not isinstance(grant, dict):
            continue
        number = _display_grant_number(
            grant.get("grant_number")
            or grant.get("award_id")
            or grant.get("funder_award_id")
        )
        if not number or _grant_is_provider_label(number):
            continue
        provider = clean_cell(grant.get("provider")).casefold()
        number_key = normalize_grant_number(number)
        if not number_key:
            continue
        key = f"{provider}|{number_key}"
        funder = clean_cell(grant.get("funder_name") or grant.get("funder"))
        agency = clean_cell(grant.get("agency"))
        existing = merged.get(key)
        if existing is None:
            merged[key] = {
                "grant_number": number,
                "funder": funder,
                "agency": agency,
                "provider": provider,
            }
            order.append(key)
            continue
        existing["grant_number"] = _prefer_grant_display(
            existing["grant_number"], number
        )
        if not existing["funder"] and funder:
            existing["funder"] = funder
        if not existing["agency"] and agency:
            existing["agency"] = agency
    return [merged[key] for key in order]


def _provider_contributed_to_export(
    provider: str,
    *,
    openalex_id: str = "",
    arxiv_id: str = "",
    arxiv_version: str = "",
    scopus_id: str = "",
    citations_by_provider: dict[str, int] | None = None,
    grants: Sequence[dict[str, Any]] | None = None,
    item_providers: Sequence[Any] | None = None,
) -> bool:
    """True when the provider actually contributed exportable work metadata."""
    key = clean_cell(provider).casefold()
    if not key:
        return False
    cites = citations_by_provider or {}
    grant_providers = {
        clean_cell(row.get("provider")).casefold()
        for row in (grants or [])
        if isinstance(row, dict)
    }
    if key == "openalex":
        if openalex_id or key in cites or key in grant_providers:
            return True
        # Stored OpenAlex corpus rows may omit openalex_id on sparse fixtures.
        return any(
            clean_cell(value).casefold() == "openalex" for value in (item_providers or [])
        )
    if key == "arxiv":
        return bool(arxiv_id or arxiv_version or key in cites or key in grant_providers)
    if key in {"scopus", "elsevier"}:
        return bool(
            scopus_id
            or "scopus" in cites
            or "elsevier" in cites
            or "scopus" in grant_providers
            or "elsevier" in grant_providers
        )
    if key == "orcid":
        return key in cites or key in grant_providers
    return key in cites or key in grant_providers


def _export_source_labels(
    *,
    openalex_id: str = "",
    arxiv_id: str = "",
    arxiv_version: str = "",
    scopus_id: str = "",
    citations_by_provider: dict[str, int] | None = None,
    grants: Sequence[dict[str, Any]] | None = None,
    item_providers: Sequence[Any] | None = None,
    work_providers: Sequence[Any] | None = None,
    source: Any = None,
) -> list[str]:
    """Build Sources from providers that contributed data. OpenAlex stays first."""
    candidates: list[str] = []
    for value in list(item_providers or []) + list(work_providers or []):
        key = clean_cell(value).casefold()
        if key == "elsevier":
            key = "scopus"
        if key and key not in candidates:
            candidates.append(key)
    source_key = clean_cell(source).casefold()
    if source_key == "elsevier":
        source_key = "scopus"
    if source_key and source_key not in candidates:
        candidates.append(source_key)
    for key in ("openalex", "arxiv", "scopus"):
        if key not in candidates:
            candidates.append(key)

    selected: list[str] = []
    for key in candidates:
        if not _provider_contributed_to_export(
            key,
            openalex_id=openalex_id,
            arxiv_id=arxiv_id,
            arxiv_version=arxiv_version,
            scopus_id=scopus_id,
            citations_by_provider=citations_by_provider,
            grants=grants,
            item_providers=item_providers,
        ):
            continue
        label = _source_label(key)
        if label and label not in selected:
            selected.append(label)
    if "OpenAlex" in selected:
        selected = ["OpenAlex"] + [label for label in selected if label != "OpenAlex"]
    return selected

def _extract_biblio_fields(source: dict[str, Any] | None) -> dict[str, str]:
    if not isinstance(source, dict):
        return {}
    biblio = source.get("biblio") if isinstance(source.get("biblio"), dict) else {}
    primary = (
        source.get("primary_location")
        if isinstance(source.get("primary_location"), dict)
        else {}
    )
    host = primary.get("source") if isinstance(primary.get("source"), dict) else {}
    first = clean_cell(biblio.get("first_page"))
    last = clean_cell(biblio.get("last_page"))
    pages = ""
    if first and last:
        pages = f"{first}-{last}"
    else:
        pages = first or last
    return {
        "publisher": clean_cell(
            source.get("publisher")
            or host.get("host_organization_name")
            or host.get("publisher")
        ),
        "volume": clean_cell(source.get("volume") or biblio.get("volume")),
        "issue": clean_cell(source.get("issue") or biblio.get("issue")),
        "pages": clean_cell(source.get("pages") or source.get("page") or pages),
        "pdf_url": clean_cell(source.get("pdf_url")),
        "open_access_url": clean_cell(
            source.get("open_access_url") or source.get("oa_url")
        ),
        "language": clean_cell(source.get("language")),
    }


def build_export_authors(
    authorships: Sequence[Any],
    *,
    author_metadata: dict[str, dict[str, Any]] | None = None,
    diagnostics: ExportDiagnostics | None = None,
) -> list[ExportAuthor]:
    """
    Build aligned ExportAuthor rows.

    Affiliation priority:
      publication authorship institutions
      → canonical author current/latest institution
      → empty
    """
    meta = author_metadata or {}
    ordered: list[ExportAuthor] = []
    seen: set[str] = set()

    for raw in authorships or []:
        if isinstance(raw, str):
            author = {"name": raw}
        elif isinstance(raw, dict):
            author = raw
        else:
            continue

        name = clean_cell(
            author.get("display_name")
            or author.get("name")
            or author.get("raw_author_name")
        )
        cid = clean_cell(author.get("canonical_author_id"))
        openalex_id = _author_openalex_id(author)
        dedupe_key = cid or (f"openalex:{openalex_id}" if openalex_id else "") or (
            f"name:{name.casefold()}" if name else ""
        )
        if dedupe_key and dedupe_key in seen:
            continue
        if dedupe_key:
            seen.add(dedupe_key)
        if not name and not cid and not openalex_id:
            continue

        stored = meta.get(cid) if cid else None
        if stored is None and openalex_id:
            stored = meta.get(f"openalex:{openalex_id}")

        if stored and stored.get("preferred_name") and not name:
            name = clean_cell(stored.get("preferred_name"))

        affiliations = _institution_names(author.get("institutions"))
        departments = _department_names(author)
        affiliation_source = "authorship" if affiliations else "missing"
        if not affiliations and stored:
            affiliations = list(stored.get("institutions") or [])
            if affiliations:
                affiliation_source = "canonical_profile"

        countries = _country_codes(author.get("countries"), author.get("institutions"))
        if not countries and stored:
            countries = list(stored.get("countries") or [])
            if not countries and stored.get("country"):
                countries = [clean_cell(stored.get("country"))]

        orcid = _author_orcid_direct(author)
        orcid_source = "authorship" if orcid else "missing"
        if not orcid and stored:
            orcid = clean_cell(stored.get("orcid"))
            if orcid:
                orcid_source = "canonical_profile"

        export_author = ExportAuthor(
            name=name,
            orcid=orcid,
            affiliations=affiliations,
            departments=departments,
            countries=countries,
            provider_author_id=openalex_id,
            canonical_author_id=cid,
            affiliation_source=affiliation_source,
            orcid_source=orcid_source,
        )
        ordered.append(export_author)

        if diagnostics is not None:
            diagnostics.authorship_count += 1
            if openalex_id:
                diagnostics.authors_with_provider_ids += 1
            if affiliations:
                diagnostics.authors_with_affiliations += 1
            if orcid:
                diagnostics.authors_with_orcid += 1
            if affiliation_source == "authorship":
                diagnostics.affiliation_from_authorship += 1
            elif affiliation_source == "canonical_profile":
                diagnostics.affiliation_from_canonical_profile += 1
            else:
                diagnostics.affiliation_missing += 1
            if orcid_source == "authorship":
                diagnostics.orcid_from_authorship += 1
            elif orcid_source == "canonical_profile":
                diagnostics.orcid_from_canonical_profile += 1
            else:
                diagnostics.orcid_missing += 1

    return ordered


# Backwards-compatible alias used by older tests.
def build_ordered_author_export_objects(
    authors: Sequence[Any],
    *,
    author_metadata: dict[str, dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    return [
        {
            "name": row.name,
            "orcid": row.orcid,
            "institutions": row.affiliations,
            "affiliations": row.affiliations,
            "country": row.countries[0] if row.countries else "",
            "countries": row.countries,
            "provider_author_id": row.provider_author_id,
        }
        for row in build_export_authors(authors, author_metadata=author_metadata)
    ]


def _format_affiliations(author: ExportAuthor) -> str:
    return AFFILIATION_DELIMITER.join(_unique_names(author.affiliations))


def _format_departments(author: ExportAuthor) -> str:
    return AFFILIATION_DELIMITER.join(_unique_names(author.departments))


def _format_countries(author: ExportAuthor) -> str:
    return AFFILIATION_DELIMITER.join(_unique_names(author.countries))


def _citations_by_provider_map(
    item: dict[str, Any],
    *,
    work_meta: dict[str, Any] | None = None,
) -> dict[str, int]:
    merged: dict[str, int] = {}
    for source in (work_meta or {}, item):
        raw = source.get("citations_by_provider")
        if not isinstance(raw, dict):
            continue
        for provider, value in raw.items():
            try:
                count = int(value) if value is not None else None
            except (TypeError, ValueError):
                count = None
            if count is None or count < 0:
                continue
            key = clean_cell(provider).casefold()
            if key and key not in merged:
                merged[key] = count
    return merged


def _format_citations_by_provider(citations: dict[str, int]) -> str:
    if not citations:
        return ""
    parts: list[str] = []
    seen: set[str] = set()
    preferred = ("openalex", "scopus", "arxiv", "orcid")
    for provider in preferred:
        if provider not in citations:
            continue
        parts.append(f"{_source_label(provider)}:{citations[provider]}")
        seen.add(provider)
    for provider in sorted(citations):
        if provider in seen:
            continue
        parts.append(f"{_source_label(provider)}:{citations[provider]}")
    return MULTI_VALUE_DELIMITER.join(parts)


def _citation_count_cell(
    item: dict[str, Any],
    *,
    work_meta: dict[str, Any] | None = None,
    diagnostics: ExportDiagnostics | None = None,
) -> str:
    from app.services.analysis.publication_enrichment import preferred_citation_count

    by_provider = _citations_by_provider_map(item, work_meta=work_meta)
    preferred = preferred_citation_count(by_provider)
    if preferred is not None:
        if diagnostics is not None:
            diagnostics.citation_from_item += 1
        return str(preferred)

    for source_name, source in (
        ("item", item),
        ("provider", work_meta or {}),
    ):
        for key in ("citation_count", "cited_by_count"):
            if key not in source:
                continue
            value = source.get(key)
            if value is None:
                continue
            if isinstance(value, float) and value != value:
                continue
            try:
                text = str(int(value))
            except (TypeError, ValueError):
                text = clean_cell(value)
                if not text:
                    continue
            if diagnostics is not None:
                if source_name == "item":
                    diagnostics.citation_from_item += 1
                else:
                    diagnostics.citation_from_provider += 1
            return text
    if diagnostics is not None:
        diagnostics.citation_missing += 1
    return ""


async def _batch_load_author_metadata(
    session: AsyncSession | None,
    items: list[dict[str, Any]],
    *,
    diagnostics: ExportDiagnostics | None = None,
) -> dict[str, dict[str, Any]]:
    if session is None:
        return {}

    canonical_ids: set[uuid.UUID] = set()
    openalex_ids: set[str] = set()
    for item in items:
        for author in item.get("authors") or []:
            if not isinstance(author, dict):
                continue
            parsed = _parse_uuid(author.get("canonical_author_id"))
            if parsed is not None:
                canonical_ids.add(parsed)
            oa = _author_openalex_id(author)
            if oa:
                openalex_ids.add(oa)

    if not canonical_ids and not openalex_ids:
        return {}

    from app.db.models import (
        AuthorProfile,
        CanonicalAuthor,
        CanonicalAuthorInstitution,
        ProviderAuthorRecord,
    )

    metadata: dict[str, dict[str, Any]] = {}
    query_count = 0

    try:
        if openalex_ids:
            provider_rows = (
                (
                    await session.execute(
                        select(ProviderAuthorRecord)
                        .where(
                            ProviderAuthorRecord.provider == "openalex",
                            ProviderAuthorRecord.provider_author_id.in_(
                                sorted(openalex_ids)
                            ),
                        )
                        .options(
                            selectinload(ProviderAuthorRecord.institutions),
                            selectinload(ProviderAuthorRecord.canonical_author),
                        )
                    )
                )
                .scalars()
                .all()
            )
            query_count += 1
            for row in provider_rows:
                if row.canonical_author_id is not None:
                    canonical_ids.add(row.canonical_author_id)
                inst_names, countries = _profile_institutions(list(row.institutions or []))
                entry = {
                    "orcid": clean_cell(row.orcid),
                    "institutions": inst_names,
                    "countries": countries,
                    "country": countries[0] if countries else "",
                    "preferred_name": clean_cell(row.display_name),
                }
                metadata[f"openalex:{row.provider_author_id}"] = entry
                if row.canonical_author_id is not None:
                    metadata.setdefault(str(row.canonical_author_id), entry)

        if canonical_ids:
            authors = (
                (
                    await session.execute(
                        select(CanonicalAuthor)
                        .where(CanonicalAuthor.id.in_(list(canonical_ids)))
                        .options(selectinload(CanonicalAuthor.provider_records))
                    )
                )
                .scalars()
                .all()
            )
            query_count += 1
            profiles = (
                (
                    await session.execute(
                        select(AuthorProfile).where(
                            AuthorProfile.canonical_author_id.in_(list(canonical_ids))
                        )
                    )
                )
                .scalars()
                .all()
            )
            query_count += 1
            institutions = (
                (
                    await session.execute(
                        select(CanonicalAuthorInstitution).where(
                            CanonicalAuthorInstitution.canonical_author_id.in_(
                                list(canonical_ids)
                            )
                        )
                    )
                )
                .scalars()
                .all()
            )
            query_count += 1

            profile_by_id = {str(row.canonical_author_id): row for row in profiles}
            institutions_by_id: dict[str, list[Any]] = {}
            for row in institutions:
                institutions_by_id.setdefault(str(row.canonical_author_id), []).append(row)

            for author in authors:
                cid = str(author.id)
                profile = profile_by_id.get(cid)
                inst_names, countries = _profile_institutions(
                    institutions_by_id.get(cid, [])
                )
                orcid = clean_cell(profile.orcid) if profile else ""
                if not orcid:
                    for record in author.provider_records or []:
                        orcid = clean_cell(getattr(record, "orcid", None))
                        if orcid:
                            break
                existing = metadata.get(cid) or {}
                merged_institutions = list(existing.get("institutions") or [])
                for name in inst_names:
                    if name.casefold() not in {n.casefold() for n in merged_institutions}:
                        merged_institutions.append(name)
                merged_countries = list(existing.get("countries") or [])
                for code in countries:
                    if code.casefold() not in {c.casefold() for c in merged_countries}:
                        merged_countries.append(code)
                metadata[cid] = {
                    "orcid": orcid or clean_cell(existing.get("orcid")),
                    "institutions": merged_institutions or inst_names,
                    "countries": merged_countries or countries,
                    "country": (merged_countries or countries or [""])[0],
                    "preferred_name": clean_cell(author.preferred_name)
                    or clean_cell(existing.get("preferred_name")),
                }
                for record in author.provider_records or []:
                    if record.provider == "openalex" and record.provider_author_id:
                        metadata[f"openalex:{record.provider_author_id}"] = metadata[cid]
    except Exception:
        logger.exception("Failed to batch-load author metadata for CSV export")
        if diagnostics is not None:
            diagnostics.database_query_count += query_count
        return metadata

    if diagnostics is not None:
        diagnostics.database_query_count += query_count
    return metadata


async def _batch_load_work_metadata(
    session: AsyncSession | None,
    items: list[dict[str, Any]],
    *,
    diagnostics: ExportDiagnostics | None = None,
) -> dict[str, dict[str, Any]]:
    if session is None:
        return {}

    work_ids: list[uuid.UUID] = []
    seen: set[uuid.UUID] = set()
    for item in items:
        parsed = _parse_uuid(item.get("canonical_work_id") or item.get("id"))
        if parsed is None or parsed in seen:
            continue
        seen.add(parsed)
        work_ids.append(parsed)
    if not work_ids:
        return {}

    from app.db.models import CanonicalWork

    try:
        works = (
            (
                await session.execute(
                    select(CanonicalWork)
                    .where(CanonicalWork.id.in_(work_ids))
                    .options(
                        selectinload(CanonicalWork.provider_records),
                        selectinload(CanonicalWork.grant_matches),
                        selectinload(CanonicalWork.authorships),
                    )
                )
            )
            .scalars()
            .all()
        )
        if diagnostics is not None:
            diagnostics.database_query_count += 1
    except Exception:
        logger.exception("Failed to batch-load work metadata for CSV export")
        return {}

    by_id: dict[str, dict[str, Any]] = {}
    for work in works:
        cid = str(work.id)
        grants: list[dict[str, Any]] = []
        topics: list[str] = []
        biblio: dict[str, str] = {}
        citation_count = None
        citations_by_provider: dict[str, int] = {}
        providers: list[str] = []
        openalex_id = ""
        scopus_id = ""
        arxiv_version = ""
        authorships: list[dict[str, Any]] = []

        for match in work.grant_matches or []:
            raw = match.raw_metadata if isinstance(match.raw_metadata, dict) else {}
            grants.append(
                {
                    "grant_number": match.grant_number,
                    "funder_name": clean_cell(raw.get("funder") or raw.get("funder_name")),
                    "agency": clean_cell(raw.get("agency")),
                    "verified": bool(match.verified),
                    "match_type": match.match_type,
                    "provider": match.provider,
                }
            )

        for record in work.provider_records or []:
            provider = clean_cell(record.provider).casefold()
            if provider and provider not in providers:
                providers.append(provider)
            if provider == "openalex" and not openalex_id:
                openalex_id = clean_cell(record.provider_work_id)
            if provider == "scopus" and not scopus_id:
                scopus_id = clean_cell(record.provider_work_id)
            raw = record.raw_metadata if isinstance(record.raw_metadata, dict) else {}
            extracted = _extract_biblio_fields(raw)
            for key, value in extracted.items():
                if value and not biblio.get(key):
                    biblio[key] = value
            topics.extend(_topic_names(raw.get("topics")))
            topics.extend(_topic_names(raw.get("categories")))
            topics.extend(_topic_names(raw.get("concepts")))
            for key in ("citation_count", "cited_by_count"):
                if raw.get(key) is None:
                    continue
                try:
                    count = int(raw.get(key))
                except (TypeError, ValueError):
                    continue
                if count < 0:
                    continue
                if provider and provider not in citations_by_provider:
                    citations_by_provider[provider] = count
                if citation_count is None and provider == "openalex":
                    citation_count = count
                break
            if provider == "scopus":
                scopus_id = clean_cell(raw.get("scopus_id") or raw.get("eid") or scopus_id)
            if provider == "arxiv" and not arxiv_version:
                arxiv_version = clean_cell(raw.get("arxiv_version") or raw.get("version"))
            for grant in raw.get("grants") or []:
                if isinstance(grant, dict):
                    row = dict(grant)
                    row.setdefault("provider", provider)
                    grants.append(row)

        if citation_count is None and citations_by_provider:
            from app.services.analysis.publication_enrichment import preferred_citation_count

            citation_count = preferred_citation_count(citations_by_provider)

        for authorship in sorted(
            work.authorships or [],
            key=lambda row: int(getattr(row, "author_position", 0) or 0),
        ):
            authorships.append(
                {
                    "display_name": authorship.display_name,
                    "name": authorship.display_name,
                    "canonical_author_id": (
                        str(authorship.canonical_author_id)
                        if authorship.canonical_author_id
                        else None
                    ),
                    "id": authorship.provider_author_id,
                    "orcid": authorship.orcid,
                    "institutions": authorship.institutions or [],
                    "institution_ids": authorship.institution_ids or [],
                    "countries": authorship.countries or [],
                    "author_position": authorship.author_position,
                    "department": (
                        authorship.raw_metadata.get("department")
                        if isinstance(authorship.raw_metadata, dict)
                        else None
                    ),
                    "raw_affiliation_text": (
                        authorship.raw_metadata.get("raw_affiliation_text")
                        if isinstance(authorship.raw_metadata, dict)
                        else None
                    ),
                    "affiliation_source": (
                        authorship.raw_metadata.get("affiliation_source")
                        if isinstance(authorship.raw_metadata, dict)
                        else None
                    ),
                    "affiliation_confidence": (
                        authorship.raw_metadata.get("affiliation_confidence")
                        if isinstance(authorship.raw_metadata, dict)
                        else None
                    ),
                    "provider_ids": {
                        "openalex": (
                            [authorship.provider_author_id]
                            if authorship.provider == "openalex"
                            and authorship.provider_author_id
                            else []
                        ),
                        "orcid": [authorship.orcid] if authorship.orcid else [],
                        "arxiv": [],
                    },
                }
            )

        by_id[cid] = {
            "doi": clean_cell(work.doi),
            "pmid": clean_cell(work.pmid),
            "arxiv_id": clean_cell(work.arxiv_id),
            "arxiv_version": arxiv_version,
            "openalex_id": openalex_id,
            "scopus_id": scopus_id,
            "title": clean_cell(work.title, collapse_whitespace=False),
            "publication_year": work.publication_year,
            "providers": providers,
            "grants": grants,
            "topics": _unique_names(topics),
            "publisher": biblio.get("publisher", ""),
            "volume": biblio.get("volume", ""),
            "issue": biblio.get("issue", ""),
            "pages": biblio.get("pages", ""),
            "pdf_url": biblio.get("pdf_url", ""),
            "open_access_url": biblio.get("open_access_url", ""),
            "language": biblio.get("language", ""),
            "citation_count": citation_count,
            "cited_by_count": citation_count,
            "citations_by_provider": citations_by_provider,
            "authorships": authorships,
        }
    return by_id


def _merge_item_authors_with_stored(
    item: dict[str, Any],
    work_meta: dict[str, Any],
) -> list[dict[str, Any]]:
    """Prefer richer stored authorships; fall back to item authors / raw metadata."""
    stored = list(work_meta.get("authorships") or [])
    live = [a for a in (item.get("authors") or []) if isinstance(a, dict) or isinstance(a, str)]
    if stored:
        # Overlay live enrichment (canonical ids) onto stored authorship order.
        by_openalex: dict[str, dict[str, Any]] = {}
        by_name: dict[str, dict[str, Any]] = {}
        for author in live:
            if not isinstance(author, dict):
                continue
            oa = _author_openalex_id(author)
            if oa:
                by_openalex[oa] = author
            name = clean_cell(author.get("display_name") or author.get("name")).casefold()
            if name:
                by_name[name] = author
        merged: list[dict[str, Any]] = []
        for authorship in stored:
            row = dict(authorship)
            oa = _author_openalex_id(row)
            live_row = by_openalex.get(oa) if oa else None
            if live_row is None:
                live_row = by_name.get(
                    clean_cell(row.get("display_name") or row.get("name")).casefold()
                )
            if live_row:
                if live_row.get("canonical_author_id") and not row.get("canonical_author_id"):
                    row["canonical_author_id"] = live_row.get("canonical_author_id")
                if not _institution_names(row.get("institutions")):
                    row["institutions"] = live_row.get("institutions") or []
                    row["countries"] = live_row.get("countries") or row.get("countries") or []
                if not _department_names(row):
                    row["department"] = live_row.get("department")
                if not _author_orcid_direct(row):
                    row["orcid"] = live_row.get("orcid")
                    row["provider_ids"] = live_row.get("provider_ids") or row.get(
                        "provider_ids"
                    )
            merged.append(row)
        return merged
    return [a if isinstance(a, dict) else {"name": a} for a in live]


def publication_item_to_row_dict(
    item: dict[str, Any],
    *,
    author_metadata: dict[str, dict[str, Any]] | None = None,
    work_metadata: dict[str, dict[str, Any]] | None = None,
    searched_grant: str | None = None,
    diagnostics: ExportDiagnostics | None = None,
) -> dict[str, str]:
    work_meta: dict[str, Any] = {}
    cid = clean_cell(item.get("canonical_work_id") or item.get("id"))
    if work_metadata and cid in work_metadata:
        work_meta = work_metadata[cid]

    authors_raw = _merge_item_authors_with_stored(item, work_meta)
    export_authors = build_export_authors(
        authors_raw,
        author_metadata=author_metadata,
        diagnostics=diagnostics,
    )

    grants = _dedupe_grants(
        list(item.get("grants") or []) + list(work_meta.get("grants") or [])
    )

    arxiv_id = clean_cell(item.get("arxiv_id") or work_meta.get("arxiv_id"))
    if not arxiv_id and str(item.get("source") or "").casefold() == "arxiv":
        arxiv_id = clean_cell(item.get("source_id"))
    arxiv_version = clean_cell(item.get("arxiv_version") or work_meta.get("arxiv_version"))
    openalex_id = clean_cell(item.get("openalex_id") or work_meta.get("openalex_id"))
    scopus_id = clean_cell(item.get("scopus_id") or work_meta.get("scopus_id"))
    if not openalex_id:
        for row in item.get("source_records") or []:
            if isinstance(row, dict) and clean_cell(row.get("provider")).casefold() == "openalex":
                openalex_id = clean_cell(row.get("provider_work_id"))
                break
    if not scopus_id:
        for row in item.get("source_records") or []:
            if isinstance(row, dict) and clean_cell(row.get("provider")).casefold() == "scopus":
                scopus_id = clean_cell(row.get("provider_work_id"))
                break

    citations_by_provider = _citations_by_provider_map(item, work_meta=work_meta)
    source_labels = _export_source_labels(
        openalex_id=openalex_id,
        arxiv_id=arxiv_id,
        arxiv_version=arxiv_version,
        scopus_id=scopus_id,
        citations_by_provider=citations_by_provider,
        grants=grants,
        item_providers=item.get("providers") or [],
        work_providers=work_meta.get("providers") or [],
        source=item.get("source"),
    )

    primary_url = clean_cell(
        item.get("url") or item.get("entry_url") or item.get("primary_url")
    )
    pdf_url = clean_cell(item.get("pdf_url") or work_meta.get("pdf_url"))
    oa_url = clean_cell(
        item.get("open_access_url")
        or item.get("oa_url")
        or work_meta.get("open_access_url")
    )
    if not oa_url and item.get("is_open_access") and pdf_url:
        oa_url = pdf_url

    topics = _topic_names(item.get("topics"))
    topics.extend(_topic_names(item.get("categories")))
    topics.extend(_topic_names(work_meta.get("topics")))

    title = clean_cell(item.get("title"), collapse_whitespace=False) or clean_cell(
        work_meta.get("title"), collapse_whitespace=False
    )
    citation = _citation_count_cell(
        item, work_meta=work_meta, diagnostics=diagnostics
    )

    if diagnostics is not None:
        diagnostics.exported_work_count += 1
        if citation != "":
            diagnostics.works_with_citations += 1
        if grants:
            diagnostics.works_with_grants += 1
        if topics:
            diagnostics.works_with_topics += 1

    oa_status = ""
    if "is_open_access" in item or "is_oa" in item:
        value = item.get("is_open_access")
        if value is None:
            value = item.get("is_oa")
        if value is not None:
            oa_status = "open" if bool(value) else "closed"

    row = {
        "Title": title,
        "Publication Date": clean_cell(
            item.get("publication_date") or item.get("published_date")
        ),
        "Publication Year": clean_cell(
            item.get("publication_year")
            if item.get("publication_year") is not None
            else work_meta.get("publication_year")
        ),
        "Journal / Venue": clean_cell(item.get("journal") or item.get("primary_source")),
        "Publication Type": clean_cell(item.get("work_type") or item.get("type")),
        "Publisher": clean_cell(item.get("publisher") or work_meta.get("publisher")),
        "Volume": clean_cell(item.get("volume") or work_meta.get("volume")),
        "Issue": clean_cell(item.get("issue") or work_meta.get("issue")),
        "Pages": clean_cell(item.get("pages") or work_meta.get("pages")),
        "Authors": join_aligned([author.name for author in export_authors]),
        "Author ORCIDs": join_aligned([author.orcid for author in export_authors]),
        "Author Affiliations": join_aligned(
            [_format_affiliations(author) for author in export_authors]
        ),
        "Author Departments": join_aligned(
            [_format_departments(author) for author in export_authors]
        ),
        "Author Countries": join_aligned(
            [_format_countries(author) for author in export_authors]
        ),
        "Citation Count": citation,
        "Citations by Provider": _format_citations_by_provider(citations_by_provider),
        "DOI": clean_cell(item.get("doi") or work_meta.get("doi")),
        "PMID": clean_cell(item.get("pmid") or work_meta.get("pmid")),
        "arXiv ID": arxiv_id,
        "arXiv Version": arxiv_version,
        "OpenAlex ID": openalex_id,
        "Scopus ID": scopus_id,
        "Primary URL": primary_url,
        "PDF URL": pdf_url,
        "Open Access Status": oa_status,
        "Open Access URL": oa_url,
        "Sources": join_unique(source_labels),
        "Grant Numbers": join_aligned([g["grant_number"] for g in grants]),
        "Grant Funders": join_aligned([g.get("funder") or "" for g in grants]),
        "Grant Agencies": join_aligned([g.get("agency") or "" for g in grants]),
        "Grant Providers": join_unique(
            [_source_label(g.get("provider")) for g in grants]
        ),
        "Research Topics": join_unique(topics),
    }
    if searched_grant:
        row["Searched Grant"] = clean_cell(searched_grant)
    return {key: escape_csv_formula(value) for key, value in row.items()}


def select_export_columns(
    rows: Sequence[dict[str, str]],
    *,
    include_searched_grant: bool = False,
) -> list[str]:
    candidates = [
        column
        for column in COLUMN_CANDIDATES
        if column != "Searched Grant" or include_searched_grant
    ]
    selected: list[str] = []
    for column in candidates:
        if column in ESSENTIAL_COLUMNS:
            selected.append(column)
            continue
        if any(clean_cell(row.get(column)) for row in rows):
            selected.append(column)
    return selected


def build_export_table(
    items: Sequence[dict[str, Any]],
    *,
    author_metadata: dict[str, dict[str, Any]] | None = None,
    work_metadata: dict[str, dict[str, Any]] | None = None,
    searched_grant: str | None = None,
    diagnostics: ExportDiagnostics | None = None,
) -> tuple[list[str], list[list[str]]]:
    rows = [
        publication_item_to_row_dict(
            item,
            author_metadata=author_metadata,
            work_metadata=work_metadata,
            searched_grant=searched_grant,
            diagnostics=diagnostics,
        )
        for item in items
    ]
    columns = select_export_columns(rows, include_searched_grant=bool(searched_grant))
    matrix = [[row.get(column, "") for column in columns] for row in rows]
    return columns, matrix


def publication_item_to_csv_row(
    item: dict[str, Any],
    *,
    author_metadata: dict[str, dict[str, Any]] | None = None,
    work_metadata: dict[str, dict[str, Any]] | None = None,
    searched_grant: str | None = None,
    columns: Sequence[str] | None = None,
) -> list[str]:
    row = publication_item_to_row_dict(
        item,
        author_metadata=author_metadata,
        work_metadata=work_metadata,
        searched_grant=searched_grant,
    )
    active = list(columns) if columns is not None else select_export_columns(
        [row], include_searched_grant=bool(searched_grant)
    )
    return [row.get(column, "") for column in active]


def iter_csv_bytes(
    items: Iterable[dict[str, Any]],
    *,
    author_metadata: dict[str, dict[str, Any]] | None = None,
    work_metadata: dict[str, dict[str, Any]] | None = None,
    searched_grant: str | None = None,
    diagnostics: ExportDiagnostics | None = None,
) -> Iterator[bytes]:
    item_list = list(items)
    columns, matrix = build_export_table(
        item_list,
        author_metadata=author_metadata,
        work_metadata=work_metadata,
        searched_grant=searched_grant,
        diagnostics=diagnostics,
    )
    buffer = io.StringIO()
    writer = csv.writer(buffer, lineterminator="\n")
    yield "\ufeff".encode("utf-8")
    writer.writerow(columns)
    yield buffer.getvalue().encode("utf-8")
    buffer.seek(0)
    buffer.truncate(0)
    for values in matrix:
        writer.writerow(values)
        chunk = buffer.getvalue()
        buffer.seek(0)
        buffer.truncate(0)
        yield chunk.encode("utf-8")


async def _enrich_export_items(
    session: AsyncSession | None,
    items: list[dict[str, Any]],
    *,
    searched_grant: str,
    provider: str,
    diagnostics: ExportDiagnostics | None = None,
) -> tuple[list[dict[str, Any]], dict[str, dict[str, Any]], dict[str, dict[str, Any]]]:
    enriched = await enrich_publication_items_authors(session, items)
    if session is not None and enriched:
        try:
            enriched = await _finalize_publication_grants(
                session,
                enriched,
                searched_grant=searched_grant,
                provider=provider,
            )
        except Exception:
            logger.exception("Failed to enrich export grants from persistence")
    author_metadata = await _batch_load_author_metadata(
        session, enriched, diagnostics=diagnostics
    )
    work_metadata = await _batch_load_work_metadata(
        session, enriched, diagnostics=diagnostics
    )
    return enriched, author_metadata, work_metadata


async def prepare_author_publication_export(
    session: AsyncSession | None,
    *,
    authors: list[dict[str, Any]],
    filters: dict[str, Any] | None = None,
) -> dict[str, Any]:
    started = time.perf_counter()
    diagnostics = ExportDiagnostics()
    normalized_filters = normalize_filters(filters)
    corpus_source = "live"
    echo_authors = authors
    items: list[dict[str, Any]] = []

    # Prefer the same verified stored corpus as table / timeline / Insights.
    if session is not None:
        from app.services.analysis.author_work_sync import AuthorWorkSyncService
        from app.services.analysis.publication_corpus import (
            load_stored_publication_filter_items,
        )
        from app.services.analysis.publication_enrichment import (
            enrich_selected_authors_publications,
        )

        if await AuthorWorkSyncService(session).fresh_verified_sync_stats(authors) is not None:
            # Soft enrichment overlays; never expands the OpenAlex corpus.
            await enrich_selected_authors_publications(session, authors)
            loaded = await load_stored_publication_filter_items(session, authors)
            by_id = {
                str(row.get("canonical_author_id") or "").strip(): row
                for row in authors
                if isinstance(row, dict) and row.get("canonical_author_id")
            }
            echo_authors = []
            for row in loaded["authors"]:
                request_row = by_id.get(str(row["canonical_author_id"])) or {}
                echo_authors.append(
                    {
                        "canonical_author_id": row["canonical_author_id"],
                        "display_name": row["display_name"],
                        "provider": request_row.get("provider") or "openalex",
                        "provider_author_id": request_row.get("provider_author_id")
                        or row["canonical_author_id"],
                    }
                )
            items = list(loaded.get("publication_items") or [])
            corpus_source = "stored_complete_corpus"

    if corpus_source != "stored_complete_corpus":
        collected = await _collect_author_publications(
            session, authors=authors, collect_all=True
        )
        echo_authors = collected["authors"]
        if collected.get("unsupported"):
            raise AuthorAnalysisError(
                collected.get("unsupported_reason")
                or "Author publication export is not supported for these authors.",
                status_code=400,
            )
        items = list(collected["items"] or [])
        corpus_source = "live"

    filename = build_authors_export_filename(
        echo_authors, filters=normalized_filters
    )
    filtered_items = apply_publication_filters(items, normalized_filters)
    filtered_items, author_metadata, work_metadata = await _enrich_export_items(
        session,
        filtered_items,
        searched_grant="",
        provider="openalex",
        diagnostics=diagnostics,
    )
    # Assemble once for diagnostics; streaming rebuilds rows cheaply from the same inputs.
    build_export_table(
        filtered_items,
        author_metadata=author_metadata,
        work_metadata=work_metadata,
        searched_grant=None,
        diagnostics=diagnostics,
    )
    diagnostics.export_duration_ms = (time.perf_counter() - started) * 1000
    logger.info(
        "author_publications_csv_export corpus_source=%s %s",
        corpus_source,
        diagnostics.as_log_dict(),
    )
    return {
        "authors": echo_authors,
        "items": filtered_items,
        "author_metadata": author_metadata,
        "work_metadata": work_metadata,
        "filename": filename,
        "row_count": len(filtered_items),
        "searched_grant": None,
        "corpus_source": corpus_source,
        "diagnostics": diagnostics.as_log_dict(),
    }


async def prepare_grant_publication_export(
    session: AsyncSession | None,
    *,
    grant_number: str,
    provider: str,
    filters: dict[str, Any] | None = None,
) -> dict[str, Any]:
    started = time.perf_counter()
    diagnostics = ExportDiagnostics()
    provider_key = str(provider or "").strip().lower()
    if provider_key not in {"openalex", "arxiv"}:
        raise GrantPublicationsError(
            "Provider must be openalex or arxiv.",
            status_code=422,
        )

    display_number = decode_grant_number(grant_number)
    if len(display_number) < 2:
        raise GrantPublicationsError(
            "Grant number must be at least 2 characters.",
            status_code=422,
        )

    collected = await _collect_grant_publications(
        session,
        grant_number=display_number,
        provider=provider_key,
    )
    normalized_filters = normalize_filters(filters)
    normalized_filters["grant_numbers"] = []
    filtered_items = apply_publication_filters(collected["items"], normalized_filters)
    filtered_items, author_metadata, work_metadata = await _enrich_export_items(
        session,
        filtered_items,
        searched_grant=display_number,
        provider=provider_key,
        diagnostics=diagnostics,
    )
    filename = build_grant_export_filename(
        display_number,
        provider=provider_key,
        filters=normalized_filters,
    )
    build_export_table(
        filtered_items,
        author_metadata=author_metadata,
        work_metadata=work_metadata,
        searched_grant=display_number,
        diagnostics=diagnostics,
    )
    diagnostics.export_duration_ms = (time.perf_counter() - started) * 1000
    logger.info("grant_publications_csv_export %s", diagnostics.as_log_dict())
    return {
        "grant_number": display_number,
        "provider": provider_key,
        "items": filtered_items,
        "author_metadata": author_metadata,
        "work_metadata": work_metadata,
        "filename": filename,
        "row_count": len(filtered_items),
        "searched_grant": display_number,
        "diagnostics": diagnostics.as_log_dict(),
    }


async def stream_publication_csv(
    prepared: dict[str, Any],
) -> AsyncIterator[bytes]:
    for chunk in iter_csv_bytes(
        prepared["items"],
        author_metadata=prepared.get("author_metadata"),
        work_metadata=prepared.get("work_metadata"),
        searched_grant=prepared.get("searched_grant"),
    ):
        yield chunk
