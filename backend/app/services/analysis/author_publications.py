"""Author publication analysis: single-author union and multi-author intersection."""

from __future__ import annotations

import base64
import calendar
import json
import logging
import re
import uuid
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.integrations.arxiv.client import (
    ArxivApiError,
    search_arxiv_publications_by_authors,
)
from app.integrations.openalex.author_works import search_works_by_author_ids
from app.integrations.openalex.client import (
    OpenAlexApiError,
    is_valid_openalex_author_id,
    _short_openalex_id,
)
from app.services.author_resolution.repository import AuthorIdentityRepository
from app.services.analysis.publication_filters import (
    apply_publication_filters,
    build_publication_facets,
    filters_key as build_filters_key,
    normalize_filters,
    search_grant_facets,
    search_venue_facets,
)
from app.services.analysis.work_authors import enrich_publication_items_authors
from app.services.work_persistence.candidate import candidate_from_provider_result
from app.services.work_persistence.service import WorkPersistenceService


logger = logging.getLogger(__name__)

METHOD_PROVIDER_IDS = "provider_author_ids"
METHOD_METADATA_NAMES = "metadata_author_name_match"


class AuthorAnalysisError(Exception):
    def __init__(self, message: str, *, status_code: int = 400) -> None:
        super().__init__(message)
        self.status_code = status_code


@dataclass
class ResolvedAuthorContext:
    canonical_author_id: str
    display_name: str
    request_provider: str
    request_provider_author_id: str
    openalex_ids: list[str] = field(default_factory=list)
    arxiv_names: list[str] = field(default_factory=list)
    provider_records_used: list[dict[str, str]] = field(default_factory=list)


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


def _authors_key(canonical_ids: list[str]) -> str:
    return ",".join(sorted(canonical_ids))


def _provider_records_key(authors: list[ResolvedAuthorContext]) -> str:
    parts: list[str] = []
    for author in authors:
        for record in sorted(
            author.provider_records_used,
            key=lambda row: (row.get("provider") or "", row.get("provider_author_id") or ""),
        ):
            parts.append(
                f"{author.canonical_author_id}:{record.get('provider')}:{record.get('provider_author_id')}"
            )
    return "|".join(parts)


async def _resolve_author(
    session: AsyncSession | None,
    author_input: dict[str, Any],
) -> ResolvedAuthorContext:
    canonical_id = str(author_input["canonical_author_id"]).strip()
    display_name = " ".join(str(author_input["display_name"]).split())
    provider = str(author_input["provider"]).strip().lower()
    provider_author_id = str(author_input["provider_author_id"]).strip()

    openalex_ids: list[str] = []
    arxiv_names: list[str] = []
    provider_records_used: list[dict[str, str]] = []

    def add_openalex(raw_id: str | None) -> None:
        short = _short_openalex_id(raw_id) or (raw_id or "").strip()
        if short and is_valid_openalex_author_id(short) and short not in openalex_ids:
            openalex_ids.append(short)
            provider_records_used.append(
                {"provider": "openalex", "provider_author_id": short}
            )

    def add_arxiv_name(name: str | None, provider_id: str | None = None) -> None:
        cleaned = " ".join((name or "").split())
        if cleaned and cleaned not in arxiv_names:
            arxiv_names.append(cleaned)
            provider_records_used.append(
                {
                    "provider": "arxiv",
                    "provider_author_id": provider_id or cleaned,
                }
            )

    # Prefer linked provider records from persistence when canonical UUID exists.
    loaded = False
    try:
        author_uuid = uuid.UUID(canonical_id)
    except (TypeError, ValueError):
        author_uuid = None

    if session is not None and author_uuid is not None:
        repo = AuthorIdentityRepository(session)
        canonical = await repo.load_canonical(author_uuid)
        if canonical is not None:
            loaded = True
            display_name = canonical.preferred_name or display_name
            for record in canonical.provider_records:
                if record.provider == "openalex":
                    add_openalex(record.provider_author_id)
                elif record.provider == "arxiv":
                    add_arxiv_name(record.display_name, record.provider_author_id)

    # Always incorporate the request provider identity (stable IDs preferred).
    if provider == "openalex":
        add_openalex(provider_author_id)
    elif provider == "arxiv":
        add_arxiv_name(display_name, provider_author_id)
    elif not loaded:
        add_arxiv_name(display_name, provider_author_id)

    if display_name and not arxiv_names and provider != "openalex":
        add_arxiv_name(display_name, provider_author_id)

    seen_keys: set[str] = set()
    unique_records: list[dict[str, str]] = []
    for row in provider_records_used:
        key = f"{row['provider']}:{row['provider_author_id']}"
        if key in seen_keys:
            continue
        seen_keys.add(key)
        unique_records.append(row)

    return ResolvedAuthorContext(
        canonical_author_id=canonical_id,
        display_name=display_name,
        request_provider=provider,
        request_provider_author_id=provider_author_id,
        openalex_ids=openalex_ids,
        arxiv_names=arxiv_names,
        provider_records_used=unique_records,
    )


def _analysis_match(*, verified: bool, method: str) -> dict[str, Any]:
    return {"verified": verified, "method": method}


def _normalize_grants(
    raw_grants: Any,
    *,
    provider: str,
    verified_default: bool,
) -> list[dict[str, Any]]:
    if not isinstance(raw_grants, list):
        return []
    grants: list[dict[str, Any]] = []
    for item in raw_grants:
        if not isinstance(item, dict):
            continue
        grants.append(
            {
                "award_id": item.get("award_id") or item.get("funder_award_id"),
                "funder_name": item.get("funder_name"),
                "verified": bool(item.get("verified", verified_default)),
                "match_type": item.get("match_type")
                or (
                    "structured_award_relationship"
                    if verified_default
                    else "metadata_text_match"
                ),
                "provider": item.get("provider") or provider,
            }
        )
    return grants


def _serialize_analysis_item(
    *,
    canonical_id: str,
    provider_result: dict[str, Any],
    provider: str,
    provider_work_id: str,
    analysis_match: dict[str, Any],
    existing_providers: list[str] | None = None,
) -> dict[str, Any]:
    row = dict(provider_result)
    row["id"] = str(canonical_id)
    row["result_id"] = str(canonical_id)
    row["canonical_work_id"] = str(canonical_id)
    row["result_type"] = "work"
    row["source"] = provider
    if provider == "openalex":
        row["openalex_id"] = provider_work_id
        row.setdefault("source_id", provider_work_id)
    elif provider == "arxiv":
        row["source_id"] = provider_work_id

    providers = list(existing_providers or [])
    if provider not in providers:
        providers.append(provider)
    row["providers"] = providers
    row["source_records"] = [
        {"provider": provider, "provider_work_id": provider_work_id}
    ]

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

    verified = bool(analysis_match.get("verified"))
    row["grants"] = _normalize_grants(
        row.get("grants"),
        provider=provider,
        verified_default=verified and provider == "openalex",
    )
    row["analysis_match"] = analysis_match
    return row


async def _canonicalize_page(
    persistence: WorkPersistenceService | None,
    *,
    provider: str,
    results: list[dict[str, Any]],
    analysis_match: dict[str, Any],
    seen_ids: set[str],
) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    for raw in results:
        if not isinstance(raw, dict):
            continue
        candidate = candidate_from_provider_result(raw, provider=provider)
        if candidate is None:
            continue

        if persistence is not None:
            canonical, _ = await persistence.resolve_candidate(candidate)
            canonical_id = str(canonical.id)
            existing = next((item for item in items if item["id"] == canonical_id), None)
            if existing is not None:
                providers = list(existing.get("providers") or [])
                if provider not in providers:
                    providers.append(provider)
                existing["providers"] = providers
                if analysis_match.get("verified") and not existing.get(
                    "analysis_match", {}
                ).get("verified"):
                    existing["analysis_match"] = analysis_match
                continue
            if canonical_id in seen_ids:
                continue
            seen_ids.add(canonical_id)
            items.append(
                _serialize_analysis_item(
                    canonical_id=canonical_id,
                    provider_result=raw,
                    provider=provider,
                    provider_work_id=candidate.provider_work_id,
                    analysis_match=analysis_match,
                )
            )
        else:
            canonical_id = f"{provider}:{candidate.provider_work_id}"
            if canonical_id in seen_ids:
                continue
            seen_ids.add(canonical_id)
            items.append(
                _serialize_analysis_item(
                    canonical_id=canonical_id,
                    provider_result=raw,
                    provider=provider,
                    provider_work_id=candidate.provider_work_id,
                    analysis_match=analysis_match,
                )
            )
    return items


_DATE_FIELD_RE = re.compile(r"^(\d{4})(?:-(\d{1,2})(?:-\d{1,2})?)?")
_MONTH_LABELS = list(calendar.month_abbr)
_MAX_MONTHLY_SPAN = 60


def _parse_publication_date_fields(
    item: dict[str, Any],
) -> tuple[int, int | None, bool] | None:
    """Return (year, month|None, has_month_precision) or None if unusable."""
    for key in ("publication_date", "published_date"):
        raw = item.get(key)
        if raw is None or raw == "":
            continue
        text = str(raw).strip()
        match = _DATE_FIELD_RE.match(text[:10])
        if not match:
            continue
        year = int(match.group(1))
        month_str = match.group(2)
        if not (1000 <= year <= 2100):
            continue
        if month_str:
            month = int(month_str)
            if 1 <= month <= 12:
                return year, month, True
        return year, None, False

    for key in ("publication_year", "year"):
        raw = item.get(key)
        if raw is None:
            continue
        try:
            year = int(raw)
        except (TypeError, ValueError):
            continue
        if 1000 <= year <= 2100:
            return year, None, False
    return None


def _month_period_key(year: int, month: int) -> str:
    return f"{year:04d}-{month:02d}"


def _month_period_label(year: int, month: int) -> str:
    return f"{_MONTH_LABELS[month]} {year}"


def _increment_month(year: int, month: int) -> tuple[int, int]:
    if month >= 12:
        return year + 1, 1
    return year, month + 1


def build_publication_timeline(
    items: list[dict[str, Any]],
) -> dict[str, Any] | None:
    """Aggregate deduplicated canonical publications into a timeline."""
    unique_items: dict[str, dict[str, Any]] = {}
    for item in items:
        canonical_id = str(
            item.get("id")
            or item.get("canonical_work_id")
            or item.get("result_id")
            or ""
        ).strip()
        if not canonical_id or canonical_id in unique_items:
            continue
        unique_items[canonical_id] = item

    total_matching = len(unique_items)
    if total_matching == 0:
        return None

    dated_by_id: dict[str, tuple[int, int | None, bool]] = {}
    for canonical_id, item in unique_items.items():
        parsed = _parse_publication_date_fields(item)
        if parsed is None:
            continue
        dated_by_id[canonical_id] = parsed

    total_dated = len(dated_by_id)
    if total_dated == 0:
        return None

    date_infos = list(dated_by_id.values())
    has_month_precision = any(info[2] for info in date_infos)
    has_year_only = any(not info[2] for info in date_infos)
    use_monthly = False
    if has_month_precision and not has_year_only:
        month_points = [
            (year, month)
            for year, month, has_month in date_infos
            if has_month and month is not None
        ]
        if month_points:
            min_year, min_month = min(month_points)
            max_year, max_month = max(month_points)
            span_months = (max_year - min_year) * 12 + (max_month - min_month) + 1
            if span_months <= _MAX_MONTHLY_SPAN:
                use_monthly = True

    counts: dict[str, int] = {}
    labels: dict[str, str] = {}

    if use_monthly:
        min_points = [
            (year, month)
            for year, month, has_month in date_infos
            if has_month and month is not None
        ]
        max_points = list(min_points)
        min_year, min_month = min(min_points)
        max_year, max_month = max(max_points)

        for year, month, has_month in date_infos:
            if not has_month or month is None:
                continue
            period = _month_period_key(year, month)
            label = _month_period_label(year, month)
            counts[period] = counts.get(period, 0) + 1
            labels[period] = label

        year, month = min_year, min_month
        while (year, month) <= (max_year, max_month):
            period = _month_period_key(year, month)
            labels.setdefault(period, _month_period_label(year, month))
            counts.setdefault(period, 0)
            year, month = _increment_month(year, month)

        interval = "month"
    else:
        years = [year for year, _, _ in date_infos]
        min_year, max_year = min(years), max(years)
        for year, _, _ in date_infos:
            period = str(year)
            counts[period] = counts.get(period, 0) + 1
            labels[period] = period
        for year in range(min_year, max_year + 1):
            period = str(year)
            labels.setdefault(period, period)
            counts.setdefault(period, 0)
        interval = "year"

    timeline_items = [
        {"period": period, "label": labels[period], "count": counts[period]}
        for period in sorted(counts.keys())
    ]
    return {
        "interval": interval,
        "total_dated_publications": total_dated,
        "total_matching_publications": total_matching,
        "items": timeline_items,
    }


async def _fetch_all_publications_for_timeline(
    *,
    persistence: WorkPersistenceService | None,
    can_openalex: bool,
    can_arxiv: bool,
    fetch_openalex,
    fetch_arxiv,
    request_id: str | None = None,
) -> list[dict[str, Any]]:
    """Collect every matching publication across provider pages for timeline aggregation.

    Provider HTTP is completed before any persistence writes so SQLite transactions
    are not held open across network waits.
    """
    rid = request_id or "-"
    provider_pages: list[tuple[str, list[dict[str, Any]], dict[str, Any]]] = []

    if can_openalex:
        oa_cursor: str | None = "*"
        page_index = 0
        while oa_cursor is not None:
            oa_page = await fetch_openalex(
                oa_cursor if oa_cursor not in (None, "") else "*"
            )
            page_index += 1
            results = [row for row in list(oa_page.get("results") or []) if isinstance(row, dict)]
            logger.info(
                "analysis_req=%s provider=openalex page=%s results=%s has_more=%s",
                rid,
                page_index,
                len(results),
                bool(oa_page.get("has_more")),
            )
            provider_pages.append(
                (
                    "openalex",
                    results,
                    _analysis_match(verified=True, method=METHOD_PROVIDER_IDS),
                )
            )
            if oa_page.get("has_more") and oa_page.get("next_cursor"):
                oa_cursor = oa_page.get("next_cursor")
            else:
                oa_cursor = None

    if can_arxiv:
        try:
            arxiv_cursor: str | None = None
            page_index = 0
            while True:
                arxiv_page = await fetch_arxiv(arxiv_cursor)
                page_index += 1
                results = [
                    row
                    for row in list(arxiv_page.get("results") or [])
                    if isinstance(row, dict)
                ]
                logger.info(
                    "analysis_req=%s provider=arxiv page=%s results=%s has_more=%s",
                    rid,
                    page_index,
                    len(results),
                    bool(arxiv_page.get("has_more")),
                )
                provider_pages.append(
                    (
                        "arxiv",
                        results,
                        _analysis_match(
                            verified=False, method=METHOD_METADATA_NAMES
                        ),
                    )
                )
                if arxiv_page.get("has_more") and arxiv_page.get("next_cursor"):
                    arxiv_cursor = arxiv_page.get("next_cursor")
                else:
                    break
        except ArxivApiError:
            if not provider_pages:
                raise
            logger.warning(
                "analysis_req=%s Skipping arXiv timeline pages after provider error",
                rid,
            )

    seen_ids: set[str] = set()
    all_items: list[dict[str, Any]] = []
    for provider, results, analysis_match in provider_pages:
        page_items = await _canonicalize_page(
            persistence,
            provider=provider,
            results=results,
            analysis_match=analysis_match,
            seen_ids=seen_ids,
        )
        all_items.extend(page_items)

    logger.info(
        "analysis_req=%s timeline_collect done pages=%s items=%s persist=%s",
        rid,
        len(provider_pages),
        len(all_items),
        persistence is not None,
    )
    return all_items


def _sort_verified_first(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return sorted(
        items,
        key=lambda item: (
            0 if item.get("analysis_match", {}).get("verified") else 1,
            -(item.get("citation_count") or item.get("cited_by_count") or 0),
            str(item.get("publication_year") or 0),
            str(item.get("title") or "").lower(),
        ),
    )


def _empty_facets() -> dict[str, Any]:
    return {"sources": [], "venues": [], "grants": [], "authors": []}


async def _collect_author_publications(
    session: AsyncSession | None,
    *,
    authors: list[dict[str, Any]],
    persist: bool = True,
    request_id: str | None = None,
) -> dict[str, Any]:
    """Resolve authors and collect the full deduplicated publication set."""
    if not authors:
        raise AuthorAnalysisError("At least one author is required.", status_code=422)

    rid = request_id or uuid.uuid4().hex[:12]
    settings = get_settings()
    resolved = [await _resolve_author(session, author) for author in authors]
    mode = "single_author" if len(resolved) == 1 else "common_publications"
    echo_authors = [
        {
            "canonical_author_id": a.canonical_author_id,
            "provider": a.request_provider,
            "provider_author_id": a.request_provider_author_id,
            "display_name": a.display_name,
        }
        for a in resolved
    ]

    all_have_openalex = all(bool(a.openalex_ids) for a in resolved)
    all_have_names = all(bool(a.display_name or a.arxiv_names) for a in resolved)
    can_openalex = all_have_openalex and settings.openalex_configured
    can_arxiv = all_have_names and settings.arxiv_configured

    logger.info(
        "analysis_req=%s collect start authors=%s mode=%s persist=%s oa=%s arxiv=%s",
        rid,
        len(resolved),
        mode,
        persist,
        can_openalex,
        can_arxiv,
    )

    if not can_openalex and not can_arxiv:
        return {
            "mode": mode,
            "authors": echo_authors,
            "items": [],
            "unsupported": True,
            "unsupported_reason": (
                "None of the selected authors have supported provider identifiers "
                "for publication analysis."
            ),
            "resolved": resolved,
            "can_openalex": False,
            "can_arxiv": False,
            "persistence": None,
            "request_id": rid,
        }

    persistence = (
        WorkPersistenceService(session)
        if persist
        and session is not None
        and settings.work_persistence_enabled
        else None
    )
    bulk_page_size = 50

    async def fetch_openalex(page_cursor: str | None) -> dict[str, Any]:
        author_id_groups = [
            list(author.openalex_ids) for author in resolved if author.openalex_ids
        ]
        return await search_works_by_author_ids(
            author_id_groups=author_id_groups,
            limit=bulk_page_size,
            cursor=page_cursor,
        )

    async def fetch_arxiv(page_cursor: str | None) -> dict[str, Any]:
        names = [
            (author.arxiv_names[0] if author.arxiv_names else author.display_name)
            for author in resolved
        ]
        return await search_arxiv_publications_by_authors(
            author_names=names,
            limit=bulk_page_size,
            cursor=page_cursor,
        )

    try:
        all_items = await _fetch_all_publications_for_timeline(
            persistence=persistence,
            can_openalex=can_openalex,
            can_arxiv=can_arxiv,
            fetch_openalex=fetch_openalex,
            fetch_arxiv=fetch_arxiv,
            request_id=rid,
        )
    except OpenAlexApiError as exc:
        raise AuthorAnalysisError(str(exc), status_code=exc.status_code) from exc
    except ArxivApiError as exc:
        raise AuthorAnalysisError(str(exc), status_code=exc.status_code) from exc

    return {
        "mode": mode,
        "authors": echo_authors,
        "items": _sort_verified_first(all_items),
        "unsupported": False,
        "unsupported_reason": None,
        "resolved": resolved,
        "can_openalex": can_openalex,
        "can_arxiv": can_arxiv,
        "persistence": persistence,
        "authors_key": _authors_key([a.canonical_author_id for a in resolved]),
        "records_key": _provider_records_key(resolved),
        "request_id": rid,
    }


async def analyze_author_publications(
    session: AsyncSession | None,
    *,
    authors: list[dict[str, Any]],
    limit: int = 20,
    cursor: str | None = None,
    filters: dict[str, Any] | None = None,
    request_id: str | None = None,
) -> dict[str, Any]:
    collected = await _collect_author_publications(
        session,
        authors=authors,
        persist=True,
        request_id=request_id,
    )
    rid = collected.get("request_id") or request_id or "-"
    mode = collected["mode"]
    echo_authors = collected["authors"]

    if collected.get("unsupported"):
        return {
            "mode": mode,
            "authors": echo_authors,
            "items": [],
            "timeline": None,
            "facets": _empty_facets(),
            "pagination": {"next_cursor": None, "has_more": False},
            "unsupported": True,
            "unsupported_reason": collected.get("unsupported_reason"),
        }

    normalized_filters = normalize_filters(filters)
    active_filters_key = build_filters_key(normalized_filters)
    authors_key = collected["authors_key"]
    records_key = collected["records_key"]
    page_limit = max(1, min(int(limit or 20), 20))
    offset = 0

    cursor_payload = _decode_cursor(cursor)
    if cursor_payload is not None:
        if cursor_payload.get("authors_key") != authors_key:
            raise AuthorAnalysisError(
                "Pagination cursor does not match the selected authors.",
                status_code=422,
            )
        if cursor_payload.get("mode") != mode:
            raise AuthorAnalysisError(
                "Pagination cursor does not match the analysis mode.",
                status_code=422,
            )
        if cursor_payload.get("filters_key", "") != active_filters_key:
            raise AuthorAnalysisError(
                "Pagination cursor does not match the active filters.",
                status_code=422,
            )
        try:
            offset = max(0, int(cursor_payload.get("offset") or 0))
        except (TypeError, ValueError):
            offset = 0

    all_items = collected["items"]
    facets = build_publication_facets(all_items)
    filtered_items = apply_publication_filters(all_items, normalized_filters)
    timeline = build_publication_timeline(filtered_items)

    page_items = filtered_items[offset : offset + page_limit]
    page_items = await enrich_publication_items_authors(session, page_items)

    next_offset = offset + len(page_items)
    has_more = next_offset < len(filtered_items)
    next_cursor = None
    if has_more:
        next_cursor = _encode_cursor(
            {
                "v": 2,
                "mode": mode,
                "authors_key": authors_key,
                "records_key": records_key,
                "filters_key": active_filters_key,
                "offset": next_offset,
                "limit": page_limit,
            }
        )

    persistence = collected.get("persistence")
    if persistence is not None and session is not None:
        try:
            await session.commit()
            logger.info("analysis_req=%s persistence commit ok items=%s", rid, len(all_items))
        except Exception:
            logger.exception("analysis_req=%s Failed to commit analysis work persistence", rid)
            await session.rollback()

    return {
        "mode": mode,
        "authors": echo_authors,
        "items": page_items,
        "timeline": timeline if cursor_payload is None else None,
        "facets": facets if cursor_payload is None else _empty_facets(),
        "pagination": {
            "next_cursor": next_cursor,
            "has_more": bool(next_cursor),
        },
        "unsupported": False,
        "unsupported_reason": None,
    }


async def search_author_publication_venues(
    session: AsyncSession | None,
    *,
    authors: list[dict[str, Any]],
    query: str = "",
    limit: int = 20,
) -> list[dict[str, Any]]:
    # Facet lookups only need the publication set; skip persistence writes.
    collected = await _collect_author_publications(
        session, authors=authors, persist=False
    )
    if collected.get("unsupported"):
        return []
    return search_venue_facets(collected["items"], query, limit=limit)


async def search_author_publication_grants(
    session: AsyncSession | None,
    *,
    authors: list[dict[str, Any]],
    query: str = "",
    limit: int = 20,
) -> list[dict[str, Any]]:
    collected = await _collect_author_publications(
        session, authors=authors, persist=False
    )
    if collected.get("unsupported"):
        return []
    return search_grant_facets(collected["items"], query, limit=limit)
