"""Normalize and enrich publication work authors with canonical IDs."""

from __future__ import annotations

import re
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.integrations.openalex.client import is_valid_openalex_author_id
from app.services.authors.summary import lookup_canonical_ids_for_openalex_authors

_OPENALEX_ID_RE = re.compile(r"^A\d{8,12}$", re.I)
_UUID_RE = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$",
    re.I,
)


def _empty_provider_ids() -> dict[str, list[str]]:
    return {"openalex": [], "orcid": [], "arxiv": []}


def _normalize_provider_ids(raw: Any) -> dict[str, list[str]]:
    provider_ids = _empty_provider_ids()
    if not isinstance(raw, dict):
        return provider_ids
    for key in ("openalex", "orcid", "arxiv"):
        values = raw.get(key)
        if isinstance(values, list):
            provider_ids[key] = sorted({str(value).strip() for value in values if value})
        elif values:
            provider_ids[key] = [str(values).strip()]
    return provider_ids


def _extract_openalex_id(author: dict[str, Any]) -> str | None:
    provider_ids = _normalize_provider_ids(author.get("provider_ids"))
    if provider_ids["openalex"]:
        return provider_ids["openalex"][0]

    raw_id = author.get("id") or author.get("openalex_id")
    if raw_id is None:
        return None
    text = str(raw_id).strip()
    if text.upper().startswith("A") and is_valid_openalex_author_id(text):
        return text
    if _OPENALEX_ID_RE.match(text):
        return text
    return None


def normalize_work_author(
    author: dict[str, Any],
    *,
    lookup: dict[str, dict[str, Any]] | None = None,
) -> dict[str, Any]:
    if not isinstance(author, dict):
        return {
            "name": "",
            "display_name": "",
            "canonical_author_id": None,
            "provider_ids": _empty_provider_ids(),
            "unresolved": True,
        }

    name = (
        author.get("name")
        or author.get("display_name")
        or ""
    )
    name = str(name).strip()
    provider_ids = _normalize_provider_ids(author.get("provider_ids"))
    openalex_id = _extract_openalex_id(author)

    canonical_author_id = author.get("canonical_author_id") or author.get("canonicalAuthorId")
    if canonical_author_id is not None:
        canonical_author_id = str(canonical_author_id).strip()
        if not _UUID_RE.match(canonical_author_id):
            canonical_author_id = None

    orcid_values = list(provider_ids.get("orcid") or [])
    if author.get("orcid"):
        orcid_values.append(str(author["orcid"]).strip())
    provider_ids["orcid"] = sorted({value for value in orcid_values if value})

    if openalex_id:
        if openalex_id not in provider_ids["openalex"]:
            provider_ids["openalex"] = sorted({*provider_ids["openalex"], openalex_id})
        if lookup and openalex_id in lookup:
            match = lookup[openalex_id]
            if not canonical_author_id and match.get("canonical_author_id"):
                canonical_author_id = match["canonical_author_id"]
            for key in ("openalex", "orcid", "arxiv"):
                provider_ids[key] = sorted(
                    {*(provider_ids.get(key) or []), *(match.get("provider_ids", {}).get(key) or [])}
                )

    unresolved = not canonical_author_id and not any(provider_ids.values())

    institutions = author.get("institutions")
    if not isinstance(institutions, list):
        institutions = []
    countries = author.get("countries")
    if not isinstance(countries, list):
        countries = []
    institution_ids = author.get("institution_ids")
    if not isinstance(institution_ids, list):
        institution_ids = []

    row = {
        "id": openalex_id or author.get("id"),
        "name": name,
        "display_name": name,
        "canonical_author_id": canonical_author_id,
        "provider_ids": provider_ids,
        "unresolved": unresolved,
        "orcid": provider_ids["orcid"][0] if provider_ids.get("orcid") else author.get("orcid"),
        "institutions": institutions,
        "institution_ids": institution_ids,
        "countries": countries,
        "author_position": author.get("author_position"),
    }
    if unresolved and not any(provider_ids.values()):
        row["unresolved"] = True
    elif not canonical_author_id and provider_ids.get("openalex"):
        row["unresolved"] = True
    else:
        row["unresolved"] = False if canonical_author_id else bool(unresolved)
    return row


async def enrich_publication_items_authors(
    session: AsyncSession | None,
    items: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    openalex_ids: set[str] = set()
    for item in items:
        for author in item.get("authors") or []:
            if isinstance(author, dict):
                openalex_id = _extract_openalex_id(author)
                if openalex_id:
                    openalex_ids.add(openalex_id)

    lookup = await lookup_canonical_ids_for_openalex_authors(session, openalex_ids)

    for item in items:
        authors = item.get("authors") or []
        item["authors"] = [
            normalize_work_author(author, lookup=lookup)
            if isinstance(author, dict)
            else normalize_work_author({"name": str(author)}, lookup=lookup)
            for author in authors
        ]
    return items
