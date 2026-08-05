"""OpenAlex author payload helpers for profile enrichment."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from app.integrations.openalex.client import (
    _as_optional_int,
    _institution_from_raw,
    _normalize_orcid,
    _short_openalex_id,
)


def extract_openalex_h_index(raw: dict[str, Any]) -> int | None:
    summary_stats = raw.get("summary_stats")
    if isinstance(summary_stats, dict):
        return _as_optional_int(summary_stats.get("h_index"))
    return None


def extract_openalex_topic_names(raw: dict[str, Any]) -> list[str]:
    topics_raw = raw.get("topics")
    if not isinstance(topics_raw, list):
        return []
    names: list[str] = []
    seen: set[str] = set()
    for item in topics_raw:
        if not isinstance(item, dict):
            continue
        name = item.get("display_name") or item.get("name")
        text = str(name).strip() if name is not None else ""
        if not text or text.lower() in seen:
            continue
        seen.add(text.lower())
        names.append(text)
    return names


def extract_openalex_affiliations(raw: dict[str, Any]) -> list[dict[str, Any]]:
    """Parse OpenAlex affiliations into canonical institution rows."""
    current_year = datetime.now(UTC).year
    rows: list[dict[str, Any]] = []
    seen_keys: set[str] = set()

    affiliations = raw.get("affiliations")
    if isinstance(affiliations, list):
        for affiliation in affiliations:
            if not isinstance(affiliation, dict):
                continue
            institution = affiliation.get("institution")
            if not isinstance(institution, dict):
                institution = affiliation
            normalized = _institution_from_raw(institution)
            if normalized is None:
                continue

            years_raw = affiliation.get("years")
            year_values: list[int] = []
            if isinstance(years_raw, list):
                for year in years_raw:
                    try:
                        year_values.append(int(year))
                    except (TypeError, ValueError):
                        continue

            is_current = affiliation.get("is_current") is True
            if not is_current and year_values and max(year_values) >= current_year:
                is_current = True

            institution_id = normalized.get("id")
            name = normalized.get("name")
            key = institution_id or f"{(name or '').lower()}|{normalized.get('country_code') or ''}"
            if key in seen_keys:
                continue
            seen_keys.add(key)

            rows.append(
                {
                    "institution_id": institution_id,
                    "institution_key": key,
                    "institution_name": name,
                    "department": None,
                    "country_code": normalized.get("country_code"),
                    "valid_from_year": min(year_values) if year_values else None,
                    "valid_to_year": max(year_values) if year_values else None,
                    "is_current": is_current,
                    "provider": "openalex",
                }
            )

    if not rows:
        last_known = raw.get("last_known_institutions")
        if isinstance(last_known, list):
            for institution in last_known:
                if not isinstance(institution, dict):
                    continue
                normalized = _institution_from_raw(institution)
                if normalized is None:
                    continue
                institution_id = normalized.get("id")
                name = normalized.get("name")
                key = institution_id or f"{(name or '').lower()}|{normalized.get('country_code') or ''}"
                if key in seen_keys:
                    continue
                seen_keys.add(key)
                rows.append(
                    {
                        "institution_id": institution_id,
                        "institution_key": key,
                        "institution_name": name,
                        "department": None,
                        "country_code": normalized.get("country_code"),
                        "valid_from_year": None,
                        "valid_to_year": None,
                        "is_current": True,
                        "provider": "openalex",
                    }
                )

    return rows


def openalex_author_id_from_raw(raw: dict[str, Any]) -> str | None:
    return _short_openalex_id(raw.get("id"))
