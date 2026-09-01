"""ORCID identifier, search-query, and provider-author candidate helpers."""

from __future__ import annotations

import re
from typing import Any

from app.services.author_resolution.candidate import AuthorCandidate, InstitutionRef, WorkRef

ORCID_URL_PREFIX = "https://orcid.org/"
ORCID_ID_RE = re.compile(r"^\d{4}-\d{4}-\d{4}-\d{3}[\dX]$", re.IGNORECASE)
_STRUCTURED_QUERY_RE = re.compile(
    r"\b(given-names|family-name|credit-name|affiliation-org-name|orcid)\s*:",
    re.IGNORECASE,
)


class OrcidNormalizeError(ValueError):
    """Raised when an ORCID identifier or search query cannot be normalized."""


def normalize_orcid_id(value: Any) -> str | None:
    """Return a bare ORCID iD (xxxx-xxxx-xxxx-xxxx) or None."""
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    if text.lower().startswith(ORCID_URL_PREFIX):
        text = text[len(ORCID_URL_PREFIX) :]
    text = text.strip().rstrip("/").split("/")[-1]
    if len(text) == 19:
        text = text[:-1] + text[-1].upper()
    if not ORCID_ID_RE.fullmatch(text):
        return None
    return text


def _escape_solr_phrase(value: str) -> str:
    return " ".join((value or "").split()).replace('"', "")


def split_given_and_family_name(display_name: str) -> tuple[str | None, str | None]:
    """Split a display name into given names and family name (last token)."""
    tokens = [part for part in " ".join((display_name or "").split()).split(" ") if part]
    if not tokens:
        return None, None
    if len(tokens) == 1:
        return None, tokens[0]
    return " ".join(tokens[:-1]), tokens[-1]


def build_orcid_author_query(
    name: str,
    *,
    affiliation: str | None = None,
) -> str:
    """
    Build a Solr query for ORCID expanded-search.

    Prefers given-names + family-name clauses. Does not collapse records by name.
    """
    cleaned = " ".join((name or "").split())
    if not cleaned:
        raise OrcidNormalizeError("Author name is required for ORCID search.")

    orcid = normalize_orcid_id(cleaned)
    if orcid:
        query = f"orcid:{orcid}"
    elif _STRUCTURED_QUERY_RE.search(cleaned):
        query = cleaned
    else:
        given, family = split_given_and_family_name(cleaned)
        if given and family:
            query = (
                f'given-names:"{_escape_solr_phrase(given)}" '
                f'AND family-name:"{_escape_solr_phrase(family)}"'
            )
        else:
            query = f'family-name:"{_escape_solr_phrase(family or given or cleaned)}"'

    affiliation_text = " ".join((affiliation or "").split())
    if affiliation_text:
        query = (
            f"{query} AND affiliation-org-name:"
            f'"{_escape_solr_phrase(affiliation_text)}"'
        )
    return query


def _text(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, dict) and "value" in value:
        return _text(value.get("value"))
    text = str(value).strip()
    return text or None


def _orcid_date(node: Any) -> str | None:
    if not isinstance(node, dict):
        return None
    year = _text((node.get("year") or {}).get("value") if isinstance(node.get("year"), dict) else node.get("year"))
    if not year:
        return None
    month = _text((node.get("month") or {}).get("value") if isinstance(node.get("month"), dict) else node.get("month"))
    day = _text((node.get("day") or {}).get("value") if isinstance(node.get("day"), dict) else node.get("day"))
    parts = [year]
    if month:
        parts.append(month.zfill(2))
        if day:
            parts.append(day.zfill(2))
    return "-".join(parts)


def parse_person_payload(payload: dict[str, Any] | None) -> dict[str, Any]:
    person = payload if isinstance(payload, dict) else {}
    name = person.get("name") if isinstance(person.get("name"), dict) else {}
    given = _text((name.get("given-names") or {}).get("value") if isinstance(name.get("given-names"), dict) else None)
    family = _text((name.get("family-name") or {}).get("value") if isinstance(name.get("family-name"), dict) else None)
    credit = _text((name.get("credit-name") or {}).get("value") if isinstance(name.get("credit-name"), dict) else None)

    other_nodes = ((person.get("other-names") or {}).get("other-name")) or person.get("other-name") or []
    if isinstance(other_nodes, dict):
        other_nodes = [other_nodes]
    other_names = [
        content
        for node in other_nodes
        if isinstance(node, dict)
        for content in [_text(node.get("content"))]
        if content
    ]

    keyword_nodes = ((person.get("keywords") or {}).get("keyword")) or person.get("keyword") or []
    if isinstance(keyword_nodes, dict):
        keyword_nodes = [keyword_nodes]
    keywords = [
        content
        for node in keyword_nodes
        if isinstance(node, dict)
        for content in [_text(node.get("content"))]
        if content
    ]

    return {
        "given_names": given,
        "family_name": family,
        "credit_name": credit,
        "other_names": other_names,
        "keywords": keywords,
        "external_ids": parse_external_identifiers(person),
    }


def parse_external_identifiers(container: dict[str, Any] | None) -> list[dict[str, str]]:
    if not isinstance(container, dict):
        return []
    nodes = (
        ((container.get("external-identifiers") or {}).get("external-identifier"))
        or container.get("external-identifier")
        or []
    )
    if isinstance(nodes, dict):
        nodes = [nodes]
    results: list[dict[str, str]] = []
    for node in nodes:
        if not isinstance(node, dict):
            continue
        id_type = _text(node.get("external-id-type"))
        value = _text(node.get("external-id-value"))
        if not id_type or not value:
            continue
        url = _text(
            (node.get("external-id-url") or {}).get("value")
            if isinstance(node.get("external-id-url"), dict)
            else node.get("external-id-url")
        )
        item = {"type": id_type, "value": value}
        if url:
            item["url"] = url
        results.append(item)
    return results


def parse_employments_payload(payload: dict[str, Any] | None) -> list[dict[str, Any]]:
    if not isinstance(payload, dict):
        return []
    groups = payload.get("affiliation-group") or []
    if isinstance(groups, dict):
        groups = [groups]
    employments: list[dict[str, Any]] = []
    for group in groups:
        summaries = (group or {}).get("summaries") or []
        if isinstance(summaries, dict):
            summaries = [summaries]
        for summary_wrap in summaries:
            if not isinstance(summary_wrap, dict):
                continue
            summary = summary_wrap.get("employment-summary") or summary_wrap
            if not isinstance(summary, dict):
                continue
            org = summary.get("organization") if isinstance(summary.get("organization"), dict) else {}
            address = org.get("address") if isinstance(org.get("address"), dict) else {}
            disambiguated = (
                org.get("disambiguated-organization")
                if isinstance(org.get("disambiguated-organization"), dict)
                else {}
            )
            name = _text(org.get("name"))
            org_id = _text(disambiguated.get("disambiguated-organization-identifier"))
            if not name and not org_id:
                continue
            employments.append(
                {
                    "id": org_id,
                    "name": name,
                    "country_code": _text(address.get("country")),
                    "city": _text(address.get("city")),
                    "region": _text(address.get("region")),
                    "department": _text(summary.get("department-name")),
                    "role": _text(summary.get("role-title")),
                    "start_date": _orcid_date(summary.get("start-date")),
                    "end_date": _orcid_date(summary.get("end-date")),
                    "disambiguation_source": _text(disambiguated.get("disambiguation-source")),
                    "source": "employment",
                }
            )
    return employments


def parse_works_payload(payload: dict[str, Any] | None) -> dict[str, Any]:
    if not isinstance(payload, dict):
        return {"works_count": 0, "works": [], "dois": []}
    groups = payload.get("group") or []
    if isinstance(groups, dict):
        groups = [groups]
    works: list[WorkRef] = []
    dois: list[str] = []
    seen_dois: set[str] = set()
    for group in groups:
        if not isinstance(group, dict):
            continue
        ext_ids = ((group.get("external-ids") or {}).get("external-id")) or []
        if isinstance(ext_ids, dict):
            ext_ids = [ext_ids]
        doi = None
        for ext in ext_ids:
            if not isinstance(ext, dict):
                continue
            if str(ext.get("external-id-type") or "").strip().lower() != "doi":
                continue
            doi = _text(ext.get("external-id-value"))
            if doi:
                break
        summaries = group.get("work-summary") or []
        if isinstance(summaries, dict):
            summaries = [summaries]
        summary = summaries[0] if summaries and isinstance(summaries[0], dict) else {}
        title = _text(
            ((summary.get("title") or {}).get("title") or {}).get("value")
            if isinstance(summary.get("title"), dict)
            else None
        )
        year_text = _text(
            ((summary.get("publication-date") or {}).get("year") or {}).get("value")
            if isinstance(summary.get("publication-date"), dict)
            else None
        )
        year = None
        if year_text:
            try:
                year = int(year_text)
            except ValueError:
                year = None
        if doi:
            key = doi.lower()
            if key not in seen_dois:
                seen_dois.add(key)
                dois.append(doi)
                works.append(WorkRef(id=doi, id_type="doi", title=title, publication_year=year))
        elif title:
            put_code = summary.get("put-code")
            works.append(
                WorkRef(
                    id=str(put_code or title),
                    id_type="orcid-put-code" if put_code else "title",
                    title=title,
                    publication_year=year,
                )
            )
    return {
        "works_count": len(groups),
        "works": works,
        "dois": dois,
    }


def _display_name(*, given: str | None, family: str | None, credit: str | None, fallback: str | None = None) -> str:
    if credit:
        return credit
    parts = [part for part in (given, family) if part]
    if parts:
        return " ".join(parts)
    return (fallback or "").strip()


def candidate_from_orcid_payloads(
    *,
    orcid: str,
    search_hit: dict[str, Any] | None = None,
    person: dict[str, Any] | None = None,
    employments_payload: dict[str, Any] | None = None,
    works_payload: dict[str, Any] | None = None,
) -> AuthorCandidate | None:
    """Map ORCID public-API payloads onto AuthorCandidate. ORCID iD is the provider id."""
    normalized = normalize_orcid_id(orcid) or normalize_orcid_id(
        (search_hit or {}).get("orcid-id")
    )
    if not normalized:
        return None

    hit = search_hit if isinstance(search_hit, dict) else {}
    person_fields = parse_person_payload(person)
    given = person_fields.get("given_names") or _text(hit.get("given-names"))
    family = person_fields.get("family_name") or _text(hit.get("family-names"))
    credit = person_fields.get("credit_name") or _text(hit.get("credit-name"))
    display_name = _display_name(given=given, family=family, credit=credit)
    if not display_name:
        return None

    aliases = list(person_fields.get("other_names") or [])
    hit_other = hit.get("other-name") or []
    if isinstance(hit_other, str):
        hit_other = [hit_other]
    for alias in hit_other:
        text = _text(alias)
        if text and text not in aliases:
            aliases.append(text)

    employments = parse_employments_payload(employments_payload)
    institutions: list[InstitutionRef] = []
    seen_inst: set[str] = set()
    for emp in employments:
        key = f"{emp.get('id') or ''}|{(emp.get('name') or '').lower()}"
        if key in seen_inst:
            continue
        seen_inst.add(key)
        institutions.append(
            InstitutionRef(
                id=emp.get("id"),
                name=emp.get("name"),
                country_code=emp.get("country_code"),
            )
        )
    if not institutions:
        hit_institutions = hit.get("institution-name") or []
        if isinstance(hit_institutions, str):
            hit_institutions = [hit_institutions]
        for name in hit_institutions:
            text = _text(name)
            if not text:
                continue
            key = text.lower()
            if key in seen_inst:
                continue
            seen_inst.add(key)
            institutions.append(InstitutionRef(name=text))

    works_info = parse_works_payload(works_payload) if works_payload is not None else {
        "works_count": None,
        "works": [],
        "dois": [],
    }

    return AuthorCandidate(
        provider="orcid",
        provider_author_id=normalized,
        display_name=display_name,
        aliases=aliases,
        institutions=institutions,
        works=list(works_info.get("works") or [])[:50],
        topics=list(person_fields.get("keywords") or []),
        orcid=normalized,
        works_count=works_info.get("works_count"),
        raw_metadata={
            "orcid": normalized,
            "given_names": given,
            "family_name": family,
            "credit_name": credit,
            "external_ids": person_fields.get("external_ids") or [],
            "employments": employments,
            "dois": works_info.get("dois") or [],
            "search_institutions": hit.get("institution-name") or [],
        },
    )
