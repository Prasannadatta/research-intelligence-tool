"""Shared ISSN normalization and extraction helpers."""

from __future__ import annotations

import re
from typing import Any

_ISSN_COMPACT_RE = re.compile(r"^[0-9]{7}[0-9Xx]$")
_ISSN_HYPHEN_RE = re.compile(r"^[0-9]{4}-[0-9]{3}[0-9Xx]$")


def compact_issn(value: Any) -> str | None:
    """Normalize an ISSN to an 8-character comparison form (no hyphen)."""
    if value is None:
        return None
    text = str(value).strip().upper().replace("ISSN", "")
    text = re.sub(r"[\s\-–—]", "", text)
    if not _ISSN_COMPACT_RE.fullmatch(text):
        return None
    return text


def format_issn(value: Any) -> str | None:
    """Return hyphenated display ISSN (XXXX-XXXX) when the value is valid."""
    compact = compact_issn(value)
    if not compact:
        return None
    return f"{compact[:4]}-{compact[4:]}"


def issn_variants(value: Any) -> tuple[str | None, str | None]:
    """Return ``(compact, display)`` for a valid ISSN, else ``(None, None)``."""
    compact = compact_issn(value)
    if not compact:
        return None, None
    return compact, f"{compact[:4]}-{compact[4:]}"


def collect_issns(*values: Any) -> list[str]:
    """Collect unique compact ISSNs from strings, lists, and nested values."""
    found: list[str] = []
    seen: set[str] = set()

    def _add(raw: Any) -> None:
        if isinstance(raw, (list, tuple, set)):
            for item in raw:
                _add(item)
            return
        if isinstance(raw, dict):
            for key in (
                "issn",
                "issn_l",
                "eissn",
                "e_issn",
                "issn_print",
                "issn_electronic",
                "print_issn",
                "electronic_issn",
            ):
                if key in raw:
                    _add(raw.get(key))
            return
        compact = compact_issn(raw)
        if compact and compact not in seen:
            seen.add(compact)
            found.append(compact)

    for value in values:
        _add(value)
    return found


def extract_issns_from_work_metadata(raw: Any) -> list[str]:
    """Pull print/eISSN values from stored canonical or OpenAlex work metadata."""
    if not isinstance(raw, dict):
        return []

    candidates: list[Any] = [
        raw.get("issn"),
        raw.get("issn_l"),
        raw.get("eissn"),
        raw.get("e_issn"),
        raw.get("issn_print"),
        raw.get("issn_electronic"),
        raw.get("print_issn"),
        raw.get("electronic_issn"),
        raw.get("issns"),
    ]

    for location_key in ("primary_location", "best_oa_location", "host_venue"):
        location = raw.get(location_key)
        if isinstance(location, dict):
            source = location.get("source") if isinstance(location.get("source"), dict) else location
            candidates.append(source)
            if isinstance(source, dict):
                candidates.append(source.get("issn"))
                candidates.append(source.get("issn_l"))

    locations = raw.get("locations")
    if isinstance(locations, list):
        for location in locations:
            if isinstance(location, dict):
                source = location.get("source")
                if isinstance(source, dict):
                    candidates.append(source)

    return collect_issns(*candidates)


def preferred_issn(values: list[str] | tuple[str, ...] | None) -> str | None:
    """Return the first valid compact ISSN from a list."""
    for value in values or []:
        compact = compact_issn(value)
        if compact:
            return compact
    return None
