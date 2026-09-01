"""Exact grant-number publication listing with filters, facets, and timeline."""

from __future__ import annotations

import base64
import json
import logging
from typing import Any
from urllib.parse import unquote

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.integrations.arxiv.client import ArxivApiError, search_arxiv_grants
from app.integrations.openalex.client import OpenAlexApiError
from app.integrations.openalex.grant_search import search_publications_for_grant_number
from app.services.analysis.author_publications import build_publication_timeline
from app.services.analysis.publication_filters import (
    apply_publication_filters,
    build_dependent_publication_facets,
    filters_key as build_filters_key,
    filters_key_matches,
    normalize_filters,
    search_author_facets,
    search_venue_facets,
)
from app.services.analysis.publication_sorting import (
    publication_sort_key,
    sort_publications,
)
from app.services.analysis.work_authors import enrich_publication_items_authors
from app.services.work_persistence.candidate import candidate_from_provider_result
from app.services.work_persistence.normalization import normalize_grant_number
from app.services.work_persistence.service import WorkPersistenceService


logger = logging.getLogger(__name__)

SUPPORTED_PROVIDERS = frozenset({"openalex", "arxiv"})
PAGE_SIZE = 20
PROVIDER_FETCH_PAGE_SIZE = 50
MAX_COLLECTED_RESULTS = 2000


class GrantPublicationsError(Exception):
    def __init__(self, message: str, *, status_code: int = 400) -> None:
        super().__init__(message)
        self.status_code = status_code


def decode_grant_number(grant_number: str) -> str:
    """Decode a path/query grant number and collapse whitespace."""
    text = unquote(str(grant_number or ""))
    return " ".join(text.split()).strip()


def _match_meta_for_provider(provider: str) -> dict[str, Any]:
    if provider == "openalex":
        return {
            "verified": True,
            "match_type": "structured_award_relationship",
        }
    return {
        "verified": False,
        "match_type": "metadata_text_match",
    }


def _empty_facets() -> dict[str, Any]:
    return {"sources": [], "institutions": [], "venues": [], "grants": [], "authors": []}


def _encode_cursor(payload: dict[str, Any]) -> str:
    raw = json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8")
    return base64.urlsafe_b64encode(raw).decode("ascii")


def _decode_cursor(cursor: str | None) -> dict[str, Any] | None:
    if cursor is None or cursor == "" or cursor == "*":
        return None
    try:
        raw = base64.urlsafe_b64decode(cursor.encode("ascii"))
        payload = json.loads(raw.decode("utf-8"))
    except (ValueError, json.JSONDecodeError, UnicodeError):
        return None
    return payload if isinstance(payload, dict) else None


def _display_grant_number(value: Any) -> str | None:
    if value is None:
        return None
    text = " ".join(str(value).split()).strip()
    return text or None


def _infer_agency(funder: str | None) -> str | None:
    if not funder:
        return None
    lowered = funder.casefold()
    if "national institutes of health" in lowered or lowered.startswith("nih"):
        return "NIH"
    if "national science foundation" in lowered or lowered == "nsf":
        return "NSF"
    return None


def _extract_raw_grant_candidates(source: dict[str, Any] | None) -> list[dict[str, Any]]:
    """Collect grant candidates from a provider work dict or raw_metadata."""
    if not isinstance(source, dict):
        return []
    candidates: list[dict[str, Any]] = []

    for key in ("grants", "awards"):
        rows = source.get(key)
        if not isinstance(rows, list):
            continue
        for row in rows:
            if not isinstance(row, dict):
                continue
            award_id = _display_grant_number(
                row.get("grant_number")
                or row.get("award_id")
                or row.get("funder_award_id")
                or row.get("display_name")
            )
            if not award_id:
                continue
            funder = _display_grant_number(
                row.get("funder")
                or row.get("funder_name")
                or row.get("funder_display_name")
            )
            if not funder:
                nested = row.get("funder")
                if isinstance(nested, dict):
                    funder = _display_grant_number(nested.get("display_name"))
            candidates.append(
                {
                    "grant_number": award_id,
                    "funder": funder,
                    "agency": _display_grant_number(row.get("agency"))
                    or _infer_agency(funder),
                    "verified": row.get("verified"),
                    "match_type": row.get("match_type"),
                    "provider": row.get("provider"),
                }
            )

    matched = _display_grant_number(source.get("matched_grant_number"))
    if matched:
        candidates.append(
            {
                "grant_number": matched,
                "funder": None,
                "agency": None,
                "verified": None,
                "match_type": None,
                "provider": None,
            }
        )
    return candidates


def _build_grant_entry(
    *,
    grant_number: str,
    searched_normalized: str,
    funder: str | None = None,
    agency: str | None = None,
    verified: bool | None = None,
    match_type: str | None = None,
    provider: str | None = None,
) -> dict[str, Any]:
    display = _display_grant_number(grant_number) or grant_number
    normalized = normalize_grant_number(display)
    is_searched = bool(normalized) and normalized == searched_normalized
    resolved_funder = _display_grant_number(funder)
    resolved_agency = _display_grant_number(agency) or _infer_agency(resolved_funder)
    return {
        "grant_number": display,
        "normalized_grant_number": normalized,
        "award_id": display,
        "funder": resolved_funder,
        "funder_name": resolved_funder,
        "agency": resolved_agency,
        "is_searched_grant": is_searched,
        "verified": bool(verified) if verified is not None else False,
        "match_type": match_type,
        "provider": provider,
    }


def _merge_grant_entries(
    candidates: list[dict[str, Any]],
    *,
    searched_grant: str,
    provider: str,
) -> list[dict[str, Any]]:
    searched_normalized = normalize_grant_number(searched_grant)
    merged: dict[str, dict[str, Any]] = {}

    for candidate in candidates:
        display = _display_grant_number(candidate.get("grant_number"))
        if not display:
            continue
        key = normalize_grant_number(display)
        if not key:
            continue
        verified = candidate.get("verified")
        if verified is None and key == searched_normalized:
            verified = provider == "openalex"
        match_type = candidate.get("match_type")
        if not match_type and key == searched_normalized:
            match_type = (
                "structured_award_relationship"
                if provider == "openalex"
                else "metadata_text_match"
            )
        entry = _build_grant_entry(
            grant_number=display,
            searched_normalized=searched_normalized,
            funder=candidate.get("funder"),
            agency=candidate.get("agency"),
            verified=verified,
            match_type=match_type,
            provider=candidate.get("provider") or provider,
        )
        existing = merged.get(key)
        if existing is None:
            merged[key] = entry
            continue
        # Prefer richer metadata / searched marking.
        if entry["is_searched_grant"]:
            existing["is_searched_grant"] = True
        if not existing.get("funder") and entry.get("funder"):
            existing["funder"] = entry["funder"]
            existing["funder_name"] = entry["funder"]
        if not existing.get("agency") and entry.get("agency"):
            existing["agency"] = entry["agency"]
        if entry.get("verified"):
            existing["verified"] = True
        if not existing.get("match_type") and entry.get("match_type"):
            existing["match_type"] = entry["match_type"]
        # Prefer original casing that matches searched display when searched.
        if entry["is_searched_grant"] and display.casefold() == searched_grant.casefold():
            existing["grant_number"] = display
            existing["award_id"] = display

    if searched_normalized and searched_normalized not in merged:
        merged[searched_normalized] = _build_grant_entry(
            grant_number=searched_grant,
            searched_normalized=searched_normalized,
            provider=provider,
            verified=provider == "openalex",
            match_type=(
                "structured_award_relationship"
                if provider == "openalex"
                else "metadata_text_match"
            ),
        )

    grants = list(merged.values())
    grants.sort(
        key=lambda row: (
            0 if row.get("is_searched_grant") else 1,
            str(row.get("grant_number") or "").casefold(),
        )
    )
    return grants


def _annotate_work_shell(
    work: dict[str, Any],
    *,
    grant_number: str,
    provider: str,
) -> dict[str, Any]:
    """Normalize work shell fields; grants are finalized after canonicalization."""
    row = dict(work)
    meta = _match_meta_for_provider(provider)
    row["matched_grant_number"] = grant_number
    row["grant_match"] = {
        "verified": bool(meta["verified"]),
        "type": meta["match_type"],
    }

    journal = row.get("journal") or row.get("primary_source")
    row["journal"] = journal
    if row.get("primary_source") is None and journal:
        row["primary_source"] = journal

    citation = row.get("citation_count")
    if citation is None:
        citation = row.get("cited_by_count")
    row["citation_count"] = citation
    row["cited_by_count"] = citation

    if not row.get("url"):
        row["url"] = row.get("entry_url") or (
            f"https://doi.org/{row['doi']}" if row.get("doi") else None
        )

    providers = list(row.get("providers") or [])
    if provider not in providers:
        providers.append(provider)
    row["providers"] = providers
    row["source"] = provider
    row["result_type"] = "work"

    # Temporary grants from this provider hit; enriched later.
    row["grants"] = _merge_grant_entries(
        _extract_raw_grant_candidates(row),
        searched_grant=grant_number,
        provider=provider,
    )
    return row


async def _load_persisted_grant_candidates(
    session: AsyncSession,
    *,
    canonical_ids: list[str],
) -> dict[str, list[dict[str, Any]]]:
    """Load grant relationships and provider metadata for canonical works."""
    import uuid

    from sqlalchemy import select
    from sqlalchemy.orm import selectinload

    from app.db.models import CanonicalWork

    by_id: dict[str, list[dict[str, Any]]] = {cid: [] for cid in canonical_ids}
    parsed_ids: list[uuid.UUID] = []
    for value in canonical_ids:
        try:
            parsed_ids.append(uuid.UUID(str(value)))
        except (TypeError, ValueError):
            continue
    if not parsed_ids:
        return by_id

    stmt = (
        select(CanonicalWork)
        .where(CanonicalWork.id.in_(parsed_ids))
        .options(
            selectinload(CanonicalWork.grant_matches),
            selectinload(CanonicalWork.provider_records),
        )
    )
    result = await session.execute(stmt)
    for work in result.scalars().all():
        cid = str(work.id)
        bucket = by_id.setdefault(cid, [])
        for match in work.grant_matches or []:
            bucket.append(
                {
                    "grant_number": match.grant_number,
                    "funder": None,
                    "agency": None,
                    "verified": bool(match.verified),
                    "match_type": match.match_type,
                    "provider": match.provider,
                }
            )
            raw = match.raw_metadata if isinstance(match.raw_metadata, dict) else None
            if raw:
                bucket.extend(_extract_raw_grant_candidates(raw))
        for record in work.provider_records or []:
            raw = record.raw_metadata if isinstance(record.raw_metadata, dict) else None
            if raw:
                bucket.extend(_extract_raw_grant_candidates(raw))
    return by_id


async def _finalize_publication_grants(
    session: AsyncSession | None,
    items: list[dict[str, Any]],
    *,
    searched_grant: str,
    provider: str,
) -> list[dict[str, Any]]:
    persisted: dict[str, list[dict[str, Any]]] = {}
    if session is not None:
        canonical_ids = [
            str(item.get("canonical_work_id") or item.get("id") or "")
            for item in items
        ]
        canonical_ids = [cid for cid in canonical_ids if cid]
        if canonical_ids:
            try:
                persisted = await _load_persisted_grant_candidates(
                    session,
                    canonical_ids=canonical_ids,
                )
            except Exception:
                logger.exception("Failed to load persisted grant relationships")
                persisted = {}

    finalized: list[dict[str, Any]] = []
    for item in items:
        row = dict(item)
        candidates = _extract_raw_grant_candidates(row)
        cid = str(row.get("canonical_work_id") or row.get("id") or "")
        if cid and cid in persisted:
            candidates.extend(persisted[cid])
        row["grants"] = _merge_grant_entries(
            candidates,
            searched_grant=searched_grant,
            provider=provider,
        )
        row["matched_grant_number"] = searched_grant
        finalized.append(row)
    return finalized


async def _canonicalize_items(
    session: AsyncSession | None,
    *,
    provider: str,
    results: list[dict[str, Any]],
    grant_number: str,
    persist: bool = True,
) -> list[dict[str, Any]]:
    settings = get_settings()
    persistence = (
        WorkPersistenceService(session)
        if persist and session is not None and settings.work_persistence_enabled
        else None
    )
    items: list[dict[str, Any]] = []
    seen: set[str] = set()

    for raw in results:
        if not isinstance(raw, dict):
            continue
        annotated = _annotate_work_shell(
            raw,
            grant_number=grant_number,
            provider=provider,
        )
        candidate = candidate_from_provider_result(annotated, provider=provider)

        if persistence is not None and candidate is not None:
            canonical, _ = await persistence.resolve_candidate(candidate)
            canonical_id = str(canonical.id)
            if canonical_id in seen:
                continue
            seen.add(canonical_id)
            annotated["id"] = canonical_id
            annotated["result_id"] = canonical_id
            annotated["canonical_work_id"] = canonical_id

            # Persist every discovered grant relationship for this work.
            for grant in annotated.get("grants") or []:
                display = _display_grant_number(grant.get("grant_number"))
                normalized = normalize_grant_number(display) if display else ""
                if not display or not normalized:
                    continue
                await persistence.repo.upsert_grant_match(
                    canonical_work_id=canonical.id,
                    provider=provider,
                    grant_number=display,
                    normalized_grant_number=normalized,
                    verified=bool(grant.get("verified")),
                    match_type=str(
                        grant.get("match_type")
                        or _match_meta_for_provider(provider)["match_type"]
                    ),
                    matched_text=None,
                    raw_metadata={
                        "funder": grant.get("funder"),
                        "agency": grant.get("agency"),
                        "is_searched_grant": grant.get("is_searched_grant"),
                    },
                )
        else:
            provider_work_id = (
                candidate.provider_work_id
                if candidate is not None
                else annotated.get("openalex_id")
                or annotated.get("source_id")
                or annotated.get("result_id")
            )
            canonical_id = f"{provider}:{provider_work_id}"
            if canonical_id in seen:
                continue
            seen.add(canonical_id)
            annotated["id"] = str(canonical_id)
            annotated["result_id"] = str(canonical_id)
            annotated["canonical_work_id"] = str(canonical_id)

        items.append(annotated)

    items = await _finalize_publication_grants(
        session,
        items,
        searched_grant=grant_number,
        provider=provider,
    )

    if persistence is not None and session is not None:
        try:
            await session.commit()
        except Exception:
            logger.exception("Failed to commit grant publication persistence")
            await session.rollback()

    return items


async def _collect_grant_publications(
    session: AsyncSession | None,
    *,
    grant_number: str,
    provider: str,
    persist: bool = True,
) -> dict[str, Any]:
    settings = get_settings()
    if provider == "openalex" and not settings.openalex_configured:
        raise GrantPublicationsError(
            "OpenAlex is not configured.",
            status_code=503,
        )
    if provider == "arxiv" and not settings.arxiv_configured:
        raise GrantPublicationsError(
            "arXiv is not configured.",
            status_code=503,
        )

    raw_results: list[dict[str, Any]] = []
    provider_cursor: str | None = None

    try:
        while len(raw_results) < MAX_COLLECTED_RESULTS:
            remaining = MAX_COLLECTED_RESULTS - len(raw_results)
            page_limit = min(PROVIDER_FETCH_PAGE_SIZE, remaining)
            if provider == "openalex":
                page = await search_publications_for_grant_number(
                    query=grant_number,
                    limit=page_limit,
                    cursor=provider_cursor,
                )
            else:
                page = await search_arxiv_grants(
                    query=grant_number,
                    limit=min(PAGE_SIZE, page_limit),
                    cursor=provider_cursor,
                )

            batch = list(page.get("results") or [])
            raw_results.extend(batch)
            next_cursor = page.get("next_cursor")
            has_more = bool(page.get("has_more") and next_cursor)
            if not has_more or not batch:
                break
            if next_cursor == provider_cursor:
                break
            provider_cursor = next_cursor
    except OpenAlexApiError as exc:
        raise GrantPublicationsError(str(exc), status_code=exc.status_code) from exc
    except ArxivApiError as exc:
        raise GrantPublicationsError(str(exc), status_code=exc.status_code) from exc

    items = await _canonicalize_items(
        session,
        provider=provider,
        results=raw_results,
        grant_number=grant_number,
        persist=persist,
    )
    return {"items": items, "grant_number": grant_number, "provider": provider}


async def list_grant_publications(
    session: AsyncSession | None,
    *,
    grant_number: str,
    provider: str,
    limit: int = PAGE_SIZE,
    cursor: str | None = None,
    filters: dict[str, Any] | None = None,
    sort_by: str | None = None,
    sort_direction: str | None = None,
) -> dict[str, Any]:
    provider_key = str(provider or "").strip().lower()
    if provider_key not in SUPPORTED_PROVIDERS:
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

    page_limit = max(1, min(int(limit or PAGE_SIZE), PAGE_SIZE))
    normalized = normalize_grant_number(display_number)
    meta = _match_meta_for_provider(provider_key)
    grant_key = f"{provider_key}:{normalized}"

    collected = await _collect_grant_publications(
        session,
        grant_number=display_number,
        provider=provider_key,
        persist=False,
    )
    all_items = await enrich_publication_items_authors(session, collected["items"])

    normalized_filters = normalize_filters(filters)
    # Grant page is already scoped to this award — ignore grant_numbers filters.
    normalized_filters["grant_numbers"] = []
    active_filters_key = build_filters_key(normalized_filters)
    active_sort_key = publication_sort_key(sort_by, sort_direction)

    offset = 0
    cursor_payload = _decode_cursor(cursor)
    if cursor_payload is not None:
        if cursor_payload.get("grant_key") != grant_key:
            raise GrantPublicationsError(
                "Pagination cursor does not match the selected grant.",
                status_code=422,
            )
        if not filters_key_matches(cursor_payload.get("filters_key", ""), active_filters_key):
            raise GrantPublicationsError(
                "Pagination cursor does not match the active filters.",
                status_code=422,
            )
        if cursor_payload.get("sort_key", "-") != active_sort_key:
            raise GrantPublicationsError(
                "Pagination cursor does not match the active sort.",
                status_code=422,
            )
        try:
            offset = max(0, int(cursor_payload.get("offset") or 0))
        except (TypeError, ValueError):
            offset = 0

    facets = build_dependent_publication_facets(all_items, normalized_filters)
    filtered_items = apply_publication_filters(all_items, normalized_filters)
    timeline = build_publication_timeline(filtered_items)
    sorted_items = sort_publications(
        filtered_items,
        sort_by=sort_by,
        sort_direction=sort_direction,
    )

    page_items = sorted_items[offset : offset + page_limit]

    next_offset = offset + len(page_items)
    has_more = next_offset < len(sorted_items)
    next_cursor = None
    if has_more:
        next_cursor = _encode_cursor(
            {
                "v": 1,
                "grant_key": grant_key,
                "filters_key": active_filters_key,
                "sort_key": active_sort_key,
                "offset": next_offset,
                "limit": page_limit,
            }
        )

    funder_name = None
    for item in all_items:
        for grant in item.get("grants") or []:
            if not isinstance(grant, dict):
                continue
            name = grant.get("funder") or grant.get("funder_name")
            if name:
                funder_name = name
                break
        if funder_name:
            break

    return {
        "grant_number": display_number,
        "normalized_grant_number": normalized,
        "provider": provider_key,
        "funder_name": funder_name,
        "verified": bool(meta["verified"]),
        "match_type": meta["match_type"],
        "items": page_items,
        "timeline": timeline if cursor_payload is None else None,
        "facets": facets if cursor_payload is None else _empty_facets(),
        "pagination": {
            "next_cursor": next_cursor if has_more else None,
            "has_more": has_more,
        },
    }


async def search_grant_publication_venues(
    session: AsyncSession | None,
    *,
    grant_number: str,
    provider: str,
    query: str = "",
    limit: int = 20,
) -> list[dict[str, Any]]:
    provider_key = str(provider or "").strip().lower()
    if provider_key not in SUPPORTED_PROVIDERS:
        raise GrantPublicationsError(
            "Provider must be openalex or arxiv.",
            status_code=422,
        )
    display_number = decode_grant_number(grant_number)
    collected = await _collect_grant_publications(
        session,
        grant_number=display_number,
        provider=provider_key,
        persist=False,
    )
    items = await enrich_publication_items_authors(session, collected["items"])
    return search_venue_facets(items, query, limit=limit)


async def search_grant_publication_authors(
    session: AsyncSession | None,
    *,
    grant_number: str,
    provider: str,
    query: str = "",
    limit: int = 20,
) -> list[dict[str, Any]]:
    provider_key = str(provider or "").strip().lower()
    if provider_key not in SUPPORTED_PROVIDERS:
        raise GrantPublicationsError(
            "Provider must be openalex or arxiv.",
            status_code=422,
        )
    display_number = decode_grant_number(grant_number)
    collected = await _collect_grant_publications(
        session,
        grant_number=display_number,
        provider=provider_key,
        persist=False,
    )
    items = await enrich_publication_items_authors(session, collected["items"])
    return search_author_facets(items, query, limit=limit)


async def build_grant_publication_facets(
    session: AsyncSession | None,
    *,
    grant_number: str,
    provider: str,
    filters: dict[str, Any] | None = None,
) -> dict[str, Any]:
    provider_key = str(provider or "").strip().lower()
    if provider_key not in SUPPORTED_PROVIDERS:
        raise GrantPublicationsError(
            "Provider must be openalex or arxiv.",
            status_code=422,
        )
    display_number = decode_grant_number(grant_number)
    collected = await _collect_grant_publications(
        session,
        grant_number=display_number,
        provider=provider_key,
        persist=False,
    )
    items = await enrich_publication_items_authors(session, collected["items"])
    return build_dependent_publication_facets(items, filters)
