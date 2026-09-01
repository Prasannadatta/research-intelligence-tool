"""Normalize and enrich publication work authors with canonical IDs."""

from __future__ import annotations

import re
import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import WorkAuthorship
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
    raw_affiliation_text = author.get("raw_affiliation_text")
    department = author.get("department")
    affiliation_source = author.get("affiliation_source")
    affiliation_confidence = author.get("affiliation_confidence")

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
        "department": str(department).strip() if department else None,
        "raw_affiliation_text": str(raw_affiliation_text).strip()
        if raw_affiliation_text
        else None,
        "affiliation_source": str(affiliation_source).strip()
        if affiliation_source
        else None,
        "affiliation_confidence": affiliation_confidence,
    }
    if unresolved and not any(provider_ids.values()):
        row["unresolved"] = True
    elif not canonical_author_id and provider_ids.get("openalex"):
        row["unresolved"] = True
    else:
        row["unresolved"] = False if canonical_author_id else bool(unresolved)
    return row


def _parse_uuid(value: Any) -> uuid.UUID | None:
    text = str(value or "").strip()
    if not _UUID_RE.match(text):
        return None
    try:
        return uuid.UUID(text)
    except (TypeError, ValueError):
        return None


def _serialize_stored_authorship(authorship: WorkAuthorship) -> dict[str, Any]:
    raw = authorship.raw_metadata if isinstance(authorship.raw_metadata, dict) else {}
    provider_ids: dict[str, list[str]] = _empty_provider_ids()
    provider = str(authorship.provider or "").lower()
    provider_author_id = str(authorship.provider_author_id or "").strip()
    if provider == "openalex" and provider_author_id:
        provider_ids["openalex"].append(provider_author_id)
    elif provider == "arxiv" and provider_author_id:
        provider_ids["arxiv"].append(provider_author_id)
    if authorship.orcid:
        provider_ids["orcid"].append(str(authorship.orcid).strip())

    return {
        "id": provider_author_id or None,
        "name": authorship.display_name,
        "display_name": authorship.display_name,
        "canonical_author_id": str(authorship.canonical_author_id)
        if authorship.canonical_author_id is not None
        else None,
        "provider_ids": provider_ids,
        "unresolved": authorship.canonical_author_id is None,
        "orcid": authorship.orcid,
        "institutions": authorship.institutions or raw.get("institutions") or [],
        "institution_ids": authorship.institution_ids or raw.get("institution_ids") or [],
        "countries": authorship.countries or raw.get("countries") or [],
        "author_position": authorship.author_position,
        "department": raw.get("department"),
        "raw_affiliation_text": raw.get("raw_affiliation_text"),
        "affiliation_source": raw.get("affiliation_source"),
        "affiliation_confidence": raw.get("affiliation_confidence"),
        "provider": provider,
    }


async def _load_stored_authorships(
    session: AsyncSession | None,
    items: list[dict[str, Any]],
) -> dict[str, list[dict[str, Any]]]:
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

    rows = (
        (
            await session.execute(
                select(WorkAuthorship)
                .where(WorkAuthorship.canonical_work_id.in_(work_ids))
                .order_by(
                    WorkAuthorship.canonical_work_id,
                    WorkAuthorship.author_position,
                )
            )
        )
        .scalars()
        .all()
    )
    by_work: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        by_work.setdefault(str(row.canonical_work_id), []).append(
            _serialize_stored_authorship(row)
        )
    return by_work


def _merge_stored_and_live_authors(
    stored: list[dict[str, Any]],
    live: list[Any],
) -> list[dict[str, Any]]:
    if not stored:
        return [
            author if isinstance(author, dict) else {"name": str(author)}
            for author in live
        ]

    live_dicts = [author for author in live if isinstance(author, dict)]
    live_by_openalex: dict[str, dict[str, Any]] = {}
    live_by_name: dict[str, dict[str, Any]] = {}
    for author in live_dicts:
        openalex_id = _extract_openalex_id(author)
        if openalex_id:
            live_by_openalex[openalex_id] = author
        name = str(author.get("display_name") or author.get("name") or "").strip()
        if name:
            live_by_name[name.casefold()] = author

    merged: list[dict[str, Any]] = []
    for authorship in stored:
        row = dict(authorship)
        openalex_id = _extract_openalex_id(row)
        live_row = live_by_openalex.get(openalex_id) if openalex_id else None
        if live_row is None:
            name = str(row.get("display_name") or row.get("name") or "").strip()
            live_row = live_by_name.get(name.casefold()) if name else None
        if live_row:
            if not row.get("canonical_author_id") and live_row.get("canonical_author_id"):
                row["canonical_author_id"] = live_row["canonical_author_id"]
            if not row.get("orcid") and live_row.get("orcid"):
                row["orcid"] = live_row["orcid"]
            if not row.get("provider_ids") and live_row.get("provider_ids"):
                row["provider_ids"] = live_row["provider_ids"]
            if not row.get("institutions") and live_row.get("institutions"):
                row["institutions"] = live_row["institutions"]
            if not row.get("countries") and live_row.get("countries"):
                row["countries"] = live_row["countries"]
            for key in (
                "department",
                "raw_affiliation_text",
                "affiliation_source",
                "affiliation_confidence",
            ):
                if row.get(key) in (None, "") and live_row.get(key) not in (None, ""):
                    row[key] = live_row[key]
        merged.append(row)
    return merged


async def enrich_publication_items_authors(
    session: AsyncSession | None,
    items: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    stored_by_work = await _load_stored_authorships(session, items)
    openalex_ids: set[str] = set()
    for item in items:
        work_id = str(item.get("canonical_work_id") or item.get("id") or "")
        authors = _merge_stored_and_live_authors(
            stored_by_work.get(work_id) or [],
            item.get("authors") or [],
        )
        item["authors"] = authors
        for author in authors:
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
