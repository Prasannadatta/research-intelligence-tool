"""Work identifier and title normalization helpers."""

from __future__ import annotations

import re
import unicodedata
from typing import Any


_DOI_PREFIX_RE = re.compile(r"^https?://(dx\.)?doi\.org/", re.IGNORECASE)
_NON_ALNUM_RE = re.compile(r"[^a-z0-9\s]+")
_WHITESPACE_RE = re.compile(r"\s+")


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


def extract_provider_work_id(result: dict[str, Any], provider: str) -> str | None:
    if provider == "openalex":
        value = result.get("openalex_id") or result.get("source_id")
    elif provider == "arxiv":
        value = result.get("source_id") or result.get("arxiv_id")
    else:
        value = result.get("source_id") or result.get("openalex_id")
    if value:
        return str(value).strip() or None
    result_id = str(result.get("result_id") or "")
    if ":" in result_id:
        return result_id.split(":", 1)[1].strip() or None
    return result_id or None
