"""Work identifier and title normalization helpers."""

from __future__ import annotations

import re
import unicodedata
from typing import Any


_DOI_PREFIX_RE = re.compile(r"^https?://(dx\.)?doi\.org/", re.IGNORECASE)
_NON_ALNUM_RE = re.compile(r"[^a-z0-9\s]+")
_WHITESPACE_RE = re.compile(r"\s+")
_DATE_FIELD_RE = re.compile(r"^(\d{4})(?:-(\d{1,2})(?:-\d{1,2})?)?")


def normalize_title(title: str | None) -> str:
    text = unicodedata.normalize("NFKD", str(title or ""))
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    text = text.casefold()
    text = _NON_ALNUM_RE.sub(" ", text)
    return _WHITESPACE_RE.sub(" ", text).strip()


def normalize_person_name(name: str | None) -> str:
    text = unicodedata.normalize("NFKD", str(name or ""))
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    text = text.casefold().replace(",", " ")
    text = _NON_ALNUM_RE.sub(" ", text)
    return _WHITESPACE_RE.sub(" ", text).strip()


def normalize_doi(doi: str | None) -> str | None:
    if not doi:
        return None
    text = str(doi).strip()
    text = _DOI_PREFIX_RE.sub("", text)
    text = text.strip().rstrip(".").casefold()
    return text or None


def normalize_arxiv_id(value: str | None) -> str | None:
    if not value:
        return None
    text = str(value).strip()
    text = re.sub(r"^https?://arxiv\.org/(abs|pdf)/", "", text, flags=re.IGNORECASE)
    text = re.sub(r"^arxiv:", "", text, flags=re.IGNORECASE)
    text = re.sub(r"v\d+$", "", text, flags=re.IGNORECASE)
    text = text.strip().casefold()
    return text or None


_ARXIV_DOI_RE = re.compile(
    r"(?:10\.48550/)?arxiv[\./](?P<id>\d{4}\.\d{4,5}|[a-z\-]+(?:\.[A-Z]{2})?/\d{7})",
    re.IGNORECASE,
)


def arxiv_id_from_doi(doi: str | None) -> str | None:
    """Extract a stable arXiv id from a DOI such as 10.48550/arXiv.2401.12345."""
    cleaned = normalize_doi(doi)
    if not cleaned:
        return None
    match = _ARXIV_DOI_RE.search(cleaned)
    if not match:
        return None
    return normalize_arxiv_id(match.group("id"))


def normalize_pmid(value: str | None) -> str | None:
    if not value:
        return None
    text = str(value).strip()
    text = re.sub(r"^pmid[:\s]*", "", text, flags=re.IGNORECASE)
    digits = re.sub(r"\D", "", text)
    return digits or None


def normalize_grant_number(value: str | None) -> str:
    text = str(value or "").strip().casefold()
    text = re.sub(r"[^a-z0-9]+", "", text)
    return text


def normalize_search_query(query: str | None, *, entity: str) -> str:
    collapsed = " ".join(str(query or "").split()).strip()
    if entity == "grants":
        return collapsed
    return collapsed.casefold()


def first_author_name(authors: Any) -> str | None:
    if not isinstance(authors, list) or not authors:
        return None
    first = authors[0]
    if isinstance(first, dict):
        return str(first.get("name") or "").strip() or None
    return str(first).strip() or None


def extract_publication_timing(
    raw: dict[str, Any] | None,
) -> tuple[int | None, int | None]:
    """Return (year, month) from publication fields.

    Month is only returned when the source has month precision. Year-only values
    return (year, None). Prefer keeping possible duplicates over fuzzy merges
    when month precision is unavailable.
    """
    if not isinstance(raw, dict):
        return None, None

    year: int | None = None
    month: int | None = None
    for key in ("publication_date", "published_date"):
        text = str(raw.get(key) or "").strip()
        if not text:
            continue
        match = _DATE_FIELD_RE.match(text[:10])
        if not match:
            continue
        parsed_year = int(match.group(1))
        if not (1000 <= parsed_year <= 2100):
            continue
        year = parsed_year
        month_str = match.group(2)
        if month_str:
            parsed_month = int(month_str)
            if 1 <= parsed_month <= 12:
                month = parsed_month
        break

    if year is None:
        for key in ("publication_year", "year"):
            value = raw.get(key)
            try:
                parsed_year = int(value) if value is not None else None
            except (TypeError, ValueError):
                parsed_year = None
            if parsed_year is not None and 1000 <= parsed_year <= 2100:
                year = parsed_year
                break

    if month is None:
        raw_month = raw.get("publication_month")
        try:
            parsed_month = int(raw_month) if raw_month is not None else None
        except (TypeError, ValueError):
            parsed_month = None
        if parsed_month is not None and 1 <= parsed_month <= 12:
            month = parsed_month

    return year, month


def extract_provider_work_id(result: dict[str, Any], provider: str) -> str | None:
    if provider == "openalex":
        value = result.get("openalex_id") or result.get("source_id")
    elif provider == "arxiv":
        value = result.get("source_id") or result.get("arxiv_id")
    elif provider == "scopus":
        value = result.get("scopus_id") or result.get("source_id") or result.get("eid")
    else:
        value = result.get("source_id") or result.get("openalex_id")
    if value:
        return str(value).strip() or None
    result_id = str(result.get("result_id") or "")
    if ":" in result_id:
        return result_id.split(":", 1)[1].strip() or None
    return result_id or None
