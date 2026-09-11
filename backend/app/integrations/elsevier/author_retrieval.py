"""Scopus Author Retrieval parsing for hover-card enrichment (not author search)."""

from __future__ import annotations

import logging
import re
from typing import Any

logger = logging.getLogger(__name__)

_ORCID_RE = re.compile(r"\d{4}-\d{4}-\d{4}-\d{3}[\dX]", re.IGNORECASE)


def _text(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, dict):
        for key in ("$", "value", "name", "preferred-name"):
            if key in value:
                return _text(value.get(key))
        return None
    text = " ".join(str(value).split()).strip()
    return text or None


def _as_list(value: Any) -> list[Any]:
    if value is None:
        return []
    if isinstance(value, list):
        return value
    return [value]


def _first_dict(value: Any) -> dict[str, Any] | None:
    if isinstance(value, dict):
        return value
    if isinstance(value, list):
        for item in value:
            if isinstance(item, dict):
                return item
    return None


def extract_orcid_from_payload(payload: dict[str, Any] | None) -> str | None:
    if not isinstance(payload, dict):
        return None
    for key in ("orcid", "ORCID", "preferred-name"):
        text = _text(payload.get(key))
        if text and _ORCID_RE.search(text):
            match = _ORCID_RE.search(text)
            return match.group(0).upper() if match else text
    profile = _first_dict(payload.get("author-profile")) or payload
    text = _text(profile.get("orcid"))
    if text and _ORCID_RE.search(text):
        match = _ORCID_RE.search(text)
        return match.group(0).upper() if match else text
    return None


def extract_scopus_author_id(payload: dict[str, Any] | None) -> str | None:
    if not isinstance(payload, dict):
        return None
    for key in ("dc:identifier", "identifier", "eid"):
        text = _text(payload.get(key))
        if not text:
            continue
        lowered = text.lower()
        if "author_id:" in lowered:
            return text.split(":", 1)[-1].strip()
        digits = re.sub(r"\D", "", text)
        if digits and key != "eid":
            return digits
    core = _first_dict(payload.get("coredata")) or {}
    return extract_scopus_author_id(core) if core else None


def _affiliation_rows_from_node(node: Any, *, current: bool) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for item in _as_list(node):
        if not isinstance(item, dict):
            continue
        affiliation_id = _text(
            item.get("@id")
            or item.get("affiliation-id")
            or item.get("id")
            or item.get("afid")
        )
        name = _text(
            item.get("affiliation-name")
            or item.get("affilname")
            or item.get("organization")
            or item.get("name")
        )
        if not name and not affiliation_id:
            ip = item.get("ip-doc") if isinstance(item.get("ip-doc"), dict) else {}
            name = _text(ip.get("afdispname") or ip.get("preferred-name"))
            affiliation_id = affiliation_id or _text(ip.get("@id") or ip.get("afid"))
        if not name and not affiliation_id:
            continue
        department = _text(
            item.get("department")
            or item.get("dept")
            or item.get("organizational-unit")
        )
        country = _text(
            item.get("affiliation-country")
            or item.get("country")
            or item.get("affiliation-country-code")
        )
        key = (
            f"scopus:{affiliation_id}"
            if affiliation_id
            else f"scopus-name:{(name or '').casefold()}"
        )
        rows.append(
            {
                "institution_key": key,
                "institution_id": affiliation_id,
                "institution_name": name,
                "department": department,
                "country_code": country,
                "is_current": current,
                "provider": "scopus",
            }
        )
    return rows


def parse_scopus_author_retrieval(payload: dict[str, Any] | None) -> dict[str, Any]:
    """Normalize Author Retrieval JSON into enrichment fields."""
    if not isinstance(payload, dict):
        return {
            "scopus_author_id": None,
            "orcid": None,
            "affiliations": [],
            "document_count": None,
            "h_index": None,
        }

    responses = payload.get("author-retrieval-response")
    entry = _first_dict(responses) or payload
    profile = _first_dict(entry.get("author-profile")) or entry
    coredata = _first_dict(entry.get("coredata")) or {}

    affiliations: list[dict[str, Any]] = []
    affiliations.extend(
        _affiliation_rows_from_node(
            profile.get("affiliation-current") or entry.get("affiliation-current"),
            current=True,
        )
    )
    affiliations.extend(
        _affiliation_rows_from_node(
            profile.get("affiliation-history") or entry.get("affiliation-history"),
            current=False,
        )
    )

    # Prefer unique keys, keep current first.
    deduped: list[dict[str, Any]] = []
    seen: set[str] = set()
    for row in affiliations:
        key = row["institution_key"]
        if key in seen:
            continue
        seen.add(key)
        deduped.append(row)

    document_count = None
    for raw in (
        coredata.get("document-count"),
        profile.get("document-count"),
        entry.get("document-count"),
    ):
        try:
            document_count = int(raw) if raw is not None else None
        except (TypeError, ValueError):
            document_count = None
        if document_count is not None:
            break

    h_index = None
    metrics = _first_dict(profile.get("h-index")) or _first_dict(entry.get("h-index"))
    if metrics:
        try:
            h_index = int(metrics.get("$") or metrics.get("value") or metrics)
        except (TypeError, ValueError):
            h_index = None

    return {
        "scopus_author_id": extract_scopus_author_id(coredata) or extract_scopus_author_id(entry),
        "orcid": extract_orcid_from_payload(profile) or extract_orcid_from_payload(entry),
        "affiliations": deduped,
        "document_count": document_count,
        "h_index": h_index,
    }
