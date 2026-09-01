"""Publication-specific author affiliation normalization.

This module intentionally avoids topic/name inference. It only promotes raw
affiliation text into department/institution fields when explicit affiliation
terms are present, and preserves the original raw text for auditability.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Callable


_WHITESPACE_RE = re.compile(r"\s+")
_PUNCT_RE = re.compile(r"[^\w\s]+", re.UNICODE)
_EXPLICIT_DEPARTMENT_RE = re.compile(
    r"\b("
    r"department|dept\.?|school\s+of|faculty\s+of|division\s+of|"
    r"institute\s+of|center\s+for|centre\s+for|laboratory\s+of|lab\s+of"
    r")\b",
    re.I,
)
_COUNTRYISH_RE = re.compile(
    r"^([A-Z]{2}|USA|U\.S\.A\.|United States|United Kingdom|Canada|China|Japan|"
    r"Germany|France|Italy|Spain|Australia|India)$",
    re.I,
)


@dataclass(frozen=True)
class AffiliationPayload:
    institutions: list[dict[str, Any]]
    institution_ids: list[str]
    countries: list[str]
    department: str | None
    raw_affiliation_text: str | None
    affiliation_source: str
    affiliation_confidence: float


def clean_affiliation_text(value: Any) -> str | None:
    if value is None:
        return None
    text = _WHITESPACE_RE.sub(" ", str(value)).strip()
    return text or None


def normalize_institution_name(value: Any) -> str:
    text = clean_affiliation_text(value) or ""
    text = _PUNCT_RE.sub(" ", text.casefold())
    return _WHITESPACE_RE.sub(" ", text).strip()


def _country(value: Any) -> str | None:
    text = clean_affiliation_text(value)
    return text.upper() if text and len(text) == 2 else text


def _raw_affiliation_strings(raw: dict[str, Any]) -> list[str]:
    values: list[Any] = []
    for key in (
        "raw_affiliation_strings",
        "raw_affiliations",
        "affiliations",
        "raw_affiliation_text",
        "affiliation",
    ):
        value = raw.get(key)
        if isinstance(value, list):
            values.extend(value)
        elif value:
            values.append(value)

    strings: list[str] = []
    seen: set[str] = set()
    for value in values:
        text = clean_affiliation_text(value)
        if not text:
            continue
        key = text.casefold()
        if key in seen:
            continue
        seen.add(key)
        strings.append(text)
    return strings


def parse_department_affiliation(raw_text: Any) -> dict[str, str | None]:
    """Conservatively parse explicit department-like affiliation text.

    Returns only fields supported by literal affiliation terms. If no explicit
    term is present, all parsed fields are empty.
    """
    text = clean_affiliation_text(raw_text)
    if not text:
        return {"department": None, "institution_name": None, "country": None}

    segments = [clean_affiliation_text(part) for part in re.split(r"[,;]", text)]
    segments = [part for part in segments if part]
    dept_index = next(
        (
            index
            for index, segment in enumerate(segments)
            if _EXPLICIT_DEPARTMENT_RE.search(segment)
        ),
        None,
    )
    if dept_index is None:
        return {"department": None, "institution_name": None, "country": None}

    department = segments[dept_index]
    tail = segments[dept_index + 1 :]
    country = None
    if tail and _COUNTRYISH_RE.match(tail[-1]):
        country = _country(tail[-1])
        tail = tail[:-1]

    institution_parts: list[str] = []
    for part in tail:
        if _EXPLICIT_DEPARTMENT_RE.search(part):
            continue
        if _COUNTRYISH_RE.match(part):
            country = country or _country(part)
            continue
        institution_parts.append(part)
    institution_name = ", ".join(institution_parts) if institution_parts else None

    return {
        "department": department,
        "institution_name": institution_name,
        "country": country,
    }


def normalize_affiliation_payload(
    raw_author: dict[str, Any] | None,
    *,
    id_normalizer: Callable[[Any], str | None] | None = None,
) -> AffiliationPayload:
    raw = raw_author if isinstance(raw_author, dict) else {}
    raw_strings = _raw_affiliation_strings(raw)
    raw_text = " | ".join(raw_strings) if raw_strings else clean_affiliation_text(
        raw.get("raw_affiliation_text")
    )

    parsed_rows: list[dict[str, str | None]] = []
    for value in raw_strings:
        parsed = parse_department_affiliation(value)
        if parsed.get("department"):
            parsed_rows.append(parsed)
    department = next(
        (row["department"] for row in parsed_rows if row.get("department")),
        clean_affiliation_text(raw.get("department")),
    )

    institutions: list[dict[str, Any]] = []
    countries: list[str] = []
    seen_country: set[str] = set()
    seen_inst: set[str] = set()

    def add_country(value: Any) -> None:
        country = _country(value)
        if not country:
            return
        key = country.casefold()
        if key in seen_country:
            return
        seen_country.add(key)
        countries.append(country)

    def add_institution(
        raw_inst: Any,
        *,
        source: str,
        confidence: float,
        default_country: Any = None,
    ) -> None:
        if isinstance(raw_inst, dict):
            inst_id = raw_inst.get("id") or raw_inst.get("institution_id") or raw_inst.get(
                "openalex_id"
            )
            inst_id = id_normalizer(inst_id) if id_normalizer else clean_affiliation_text(inst_id)
            name = clean_affiliation_text(
                raw_inst.get("display_name")
                or raw_inst.get("name")
                or raw_inst.get("institution_name")
            )
            country = _country(
                raw_inst.get("country_code")
                or raw_inst.get("country")
                or default_country
            )
            inst_type = clean_affiliation_text(raw_inst.get("type"))
            raw_department = clean_affiliation_text(raw_inst.get("department"))
        else:
            inst_id = None
            name = clean_affiliation_text(raw_inst)
            country = _country(default_country)
            inst_type = None
            raw_department = None

        if not inst_id and not name:
            return
        key = f"id:{inst_id.casefold()}" if inst_id else (
            f"name:{normalize_institution_name(name)}|country:{(country or '').casefold()}"
        )
        if key in seen_inst:
            add_country(country)
            return
        seen_inst.add(key)

        entry = {
            "id": inst_id,
            "name": name or inst_id,
            "country_code": country,
            "type": inst_type,
            "department": raw_department or department,
            "source": source,
            "affiliation_source": source,
            "affiliation_confidence": confidence,
        }
        if raw_text:
            entry["raw_affiliation_text"] = raw_text
        institutions.append(entry)
        add_country(country)

    raw_institutions = raw.get("institutions")
    if isinstance(raw_institutions, list):
        for institution in raw_institutions:
            add_institution(
                institution,
                source="structured_authorship",
                confidence=0.95,
            )

    raw_countries = raw.get("countries")
    if isinstance(raw_countries, list):
        for value in raw_countries:
            add_country(value)

    if not institutions:
        for parsed in parsed_rows:
            if parsed.get("country"):
                add_country(parsed["country"])
            if parsed.get("institution_name"):
                add_institution(
                    parsed["institution_name"],
                    source="raw_affiliation_text",
                    confidence=0.6,
                    default_country=parsed.get("country"),
                )

    institution_ids = [
        str(entry["id"])
        for entry in institutions
        if entry.get("id")
    ]
    source = "structured_authorship" if institutions else "missing"
    confidence = 0.0
    if institutions:
        source = str(institutions[0].get("affiliation_source") or "structured_authorship")
        confidence = float(institutions[0].get("affiliation_confidence") or 0.0)
    elif raw_text:
        source = "raw_affiliation_text"
        confidence = 0.4

    return AffiliationPayload(
        institutions=institutions,
        institution_ids=institution_ids,
        countries=countries,
        department=department,
        raw_affiliation_text=raw_text,
        affiliation_source=source,
        affiliation_confidence=confidence,
    )
