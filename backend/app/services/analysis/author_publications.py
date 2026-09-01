"""Author publication analysis: single-author union and multi-author intersection."""

from __future__ import annotations

import base64
import calendar
import json
import logging
import re
import time
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
    build_dependent_publication_facets,
    filters_key as build_filters_key,
    filters_key_matches,
    normalize_filters,
    search_grant_facets,
    search_venue_facets,
)
from app.services.analysis.publication_sorting import (
    publication_sort_key,
    sort_publications,
)
from app.services.analysis.work_authors import enrich_publication_items_authors
from app.services.work_persistence.candidate import candidate_from_provider_result
from app.services.work_persistence.service import WorkPersistenceService


logger = logging.getLogger(__name__)

METHOD_PROVIDER_IDS = "provider_author_ids"


def _stage_ms(started: float) -> float:
    return round((time.perf_counter() - started) * 1000, 1)


def _log_stage(rid: str, stage: str, started: float, **fields: Any) -> None:
    extras = " ".join(f"{key}={value}" for key, value in fields.items())
    logger.info(
        "analysis_timing req=%s stage=%s ms=%s %s",
        rid,
        stage,
        _stage_ms(started),
        extras,
    )


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

    # Only query arXiv when the author has an arXiv provider identity.
    if provider == "openalex":
        add_openalex(provider_author_id)
    elif provider == "arxiv":
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


def _provider_has_more(page: dict[str, Any]) -> bool:
    return bool(page.get("has_more") and page.get("next_cursor"))


def _provider_total_count(page: dict[str, Any] | None) -> int | None:
    if not isinstance(page, dict):
        return None
    raw = page.get("count")
    if isinstance(raw, bool) or raw is None:
        return None
    try:
        value = int(raw)
    except (TypeError, ValueError):
        return None
    return value if value >= 0 else None


async def _fetch_one_provider_page(
    *,
    persistence: WorkPersistenceService | None,
    provider: str,
    fetch_page,
    cursor: str | None,
    analysis_match: dict[str, Any],
    seen_ids: set[str],
    request_id: str,
    page_index: int,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    page = await fetch_page(cursor)
    results = [row for row in list(page.get("results") or []) if isinstance(row, dict)]
    logger.info(
        "analysis_req=%s provider=%s page=%s results=%s has_more=%s",
        request_id,
        provider,
        page_index,
        len(results),
        bool(page.get("has_more")),
    )
    items = await _canonicalize_page(
        persistence,
        provider=provider,
        results=results,
        analysis_match=analysis_match,
        seen_ids=seen_ids,
    )
    return items, page


async def _fetch_publication_pages(
    *,
    persistence: WorkPersistenceService | None,
    can_openalex: bool,
    can_arxiv: bool,
    fetch_openalex,
    fetch_arxiv,
    collect_all: bool = False,
    stage: str | None = None,
    oa_cursor: str | None = None,
    arxiv_cursor: str | None = None,
    request_id: str | None = None,
) -> dict[str, Any]:
    """Fetch live publications. Default: one provider page. Export may collect all.

    Provider HTTP finishes before persistence writes so SQLite transactions are
    not held across network waits.
    """
    rid = request_id or "-"
    seen_ids: set[str] = set()
    all_items: list[dict[str, Any]] = []
    persist_started = time.perf_counter()
    current_stage = stage or ("openalex" if can_openalex else "arxiv")
    current_oa = oa_cursor if oa_cursor not in (None, "") else "*"
    current_arxiv = arxiv_cursor
    oa_pages = 0
    arxiv_pages = 0
    next_stage = current_stage
    next_oa_cursor: str | None = None
    next_arxiv_cursor: str | None = None
    replay_oa_cursor = current_oa if can_openalex and current_stage == "openalex" else None
    replay_arxiv_cursor = current_arxiv if current_stage == "arxiv" else None
    provider_has_more = False
    provider_total_count: int | None = None

    async def _openalex_page() -> tuple[list[dict[str, Any]], bool, str | None]:
        nonlocal oa_pages, provider_total_count
        oa_pages += 1
        items, page = await _fetch_one_provider_page(
            persistence=persistence,
            provider="openalex",
            fetch_page=fetch_openalex,
            cursor=current_oa,
            analysis_match=_analysis_match(verified=True, method=METHOD_PROVIDER_IDS),
            seen_ids=seen_ids,
            request_id=rid,
            page_index=oa_pages,
        )
        if provider_total_count is None:
            provider_total_count = _provider_total_count(page)
        has_more = _provider_has_more(page)
        return items, has_more, page.get("next_cursor") if has_more else None

    async def _arxiv_page() -> tuple[list[dict[str, Any]], bool, str | None]:
        nonlocal arxiv_pages
        arxiv_pages += 1
        items, page = await _fetch_one_provider_page(
            persistence=persistence,
            provider="arxiv",
            fetch_page=fetch_arxiv,
            cursor=current_arxiv,
            analysis_match=_analysis_match(verified=False, method=METHOD_METADATA_NAMES),
            seen_ids=seen_ids,
            request_id=rid,
            page_index=arxiv_pages,
        )
        has_more = _provider_has_more(page)
        return items, has_more, page.get("next_cursor") if has_more else None

    oa_started = time.perf_counter()
    arxiv_started = time.perf_counter()
    try:
        if collect_all:
            if can_openalex:
                current_oa = "*"
                while True:
                    items, has_more, nxt = await _openalex_page()
                    all_items.extend(items)
                    if not has_more:
                        break
                    current_oa = nxt
            if can_arxiv:
                current_arxiv = None
                while True:
                    items, has_more, nxt = await _arxiv_page()
                    all_items.extend(items)
                    if not has_more:
                        break
                    current_arxiv = nxt
            provider_has_more = False
            next_stage = "done"
        elif current_stage == "arxiv" or (can_arxiv and not can_openalex):
            items, has_more, nxt = await _arxiv_page()
            all_items.extend(items)
            provider_has_more = has_more
            next_arxiv_cursor = nxt
            next_stage = "arxiv" if has_more else "done"
        elif can_openalex:
            items, has_more, nxt = await _openalex_page()
            all_items.extend(items)
            if has_more:
                provider_has_more = True
                next_oa_cursor = nxt
                next_stage = "openalex"
            elif can_arxiv:
                provider_has_more = True
                next_stage = "arxiv"
                next_arxiv_cursor = None
            else:
                next_stage = "done"
        elif can_arxiv:
            items, has_more, nxt = await _arxiv_page()
            all_items.extend(items)
            provider_has_more = has_more
            next_arxiv_cursor = nxt
            next_stage = "arxiv" if has_more else "done"
    except ArxivApiError:
        if not all_items:
            raise
        logger.warning(
            "analysis_req=%s Skipping arXiv page after provider error",
            rid,
        )
        provider_has_more = False
        next_stage = "done"

    _log_stage(rid, "openalex_http_pages", oa_started, pages=oa_pages, skipped=int(oa_pages == 0))
    _log_stage(rid, "arxiv_http_pages", arxiv_started, pages=arxiv_pages, skipped=int(arxiv_pages == 0))
    _log_stage(
        rid,
        "canonicalize_persist",
        persist_started,
        items=len(all_items),
        persist=bool(persistence),
        collect_all=collect_all,
        in_transaction=bool(persistence is not None and persistence.session.in_transaction()),
    )
    logger.info(
        "analysis_req=%s publication_collect done items=%s persist=%s collect_all=%s has_more=%s",
        rid,
        len(all_items),
        persistence is not None,
        collect_all,
        provider_has_more,
    )
    return {
        "items": all_items,
        "provider_has_more": provider_has_more,
        "provider_total_count": provider_total_count,
        "next_stage": next_stage,
        "next_oa_cursor": next_oa_cursor,
        "next_arxiv_cursor": next_arxiv_cursor,
        "replay_oa_cursor": replay_oa_cursor,
        "replay_arxiv_cursor": replay_arxiv_cursor,
        "replay_stage": current_stage,
    }


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
    return {"sources": [], "institutions": [], "venues": [], "grants": [], "authors": []}


async def _collect_author_publications(
    session: AsyncSession | None,
    *,
    authors: list[dict[str, Any]],
    persist: bool = True,
    request_id: str | None = None,
    collect_all: bool = False,
    stage: str | None = None,
    oa_cursor: str | None = None,
    arxiv_cursor: str | None = None,
) -> dict[str, Any]:
    """Resolve authors and collect publications. Default: one live provider page."""
    if not authors:
        raise AuthorAnalysisError("At least one author is required.", status_code=422)

    rid = request_id or uuid.uuid4().hex[:12]
    collect_started = time.perf_counter()
    settings = get_settings()
    resolve_started = time.perf_counter()
    resolved = [await _resolve_author(session, author) for author in authors]
    _log_stage(
        rid,
        "resolve_authors",
        resolve_started,
        authors=len(resolved),
        persist=persist,
        oa_ids=sum(len(a.openalex_ids) for a in resolved),
        arxiv_names=sum(len(a.arxiv_names) for a in resolved),
    )
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
    all_have_arxiv_identity = all(bool(a.arxiv_names) for a in resolved)
    can_openalex = all_have_openalex and settings.openalex_configured
    can_arxiv = all_have_arxiv_identity and settings.arxiv_configured

    logger.info(
        "analysis_req=%s collect start authors=%s mode=%s persist=%s oa=%s arxiv=%s collect_all=%s",
        rid,
        len(resolved),
        mode,
        persist,
        can_openalex,
        can_arxiv,
        collect_all,
    )

    empty_fetch = {
        "provider_has_more": False,
        "provider_total_count": None,
        "next_stage": "done",
        "next_oa_cursor": None,
        "next_arxiv_cursor": None,
        "replay_oa_cursor": None,
        "replay_arxiv_cursor": None,
        "replay_stage": stage or "openalex",
    }

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
            **empty_fetch,
        }

    persistence = (
        WorkPersistenceService(session)
        if persist
        and session is not None
        and settings.work_persistence_enabled
        else None
    )
    page_size = 20
    provider_calls = {"openalex": 0, "arxiv": 0, "orcid": 0, "scopus": 0}

    async def fetch_openalex(page_cursor: str | None) -> dict[str, Any]:
        provider_calls["openalex"] += 1
        author_id_groups = [
            list(author.openalex_ids) for author in resolved if author.openalex_ids
        ]
        return await search_works_by_author_ids(
            author_id_groups=author_id_groups,
            limit=page_size,
            cursor=page_cursor,
        )

    async def fetch_arxiv(page_cursor: str | None) -> dict[str, Any]:
        provider_calls["arxiv"] += 1
        names = [
            (author.arxiv_names[0] if author.arxiv_names else author.display_name)
            for author in resolved
        ]
        return await search_arxiv_publications_by_authors(
            author_names=names,
            limit=page_size,
            cursor=page_cursor,
        )

    try:
        fetched = await _fetch_publication_pages(
            persistence=persistence,
            can_openalex=can_openalex,
            can_arxiv=can_arxiv,
            fetch_openalex=fetch_openalex,
            fetch_arxiv=fetch_arxiv,
            collect_all=collect_all,
            stage=stage,
            oa_cursor=oa_cursor,
            arxiv_cursor=arxiv_cursor,
            request_id=rid,
        )
    except OpenAlexApiError as exc:
        raise AuthorAnalysisError(str(exc), status_code=exc.status_code) from exc
    except ArxivApiError as exc:
        raise AuthorAnalysisError(str(exc), status_code=exc.status_code) from exc

    all_items = fetched["items"]
    _log_stage(
        rid,
        "collect_total",
        collect_started,
        items=len(all_items),
        persist=persist,
        oa=can_openalex,
        arxiv=can_arxiv,
        provider_calls=provider_calls,
        collect_all=collect_all,
    )
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
        "provider_has_more": fetched["provider_has_more"],
        "next_stage": fetched["next_stage"],
        "next_oa_cursor": fetched["next_oa_cursor"],
        "next_arxiv_cursor": fetched["next_arxiv_cursor"],
        "replay_oa_cursor": fetched["replay_oa_cursor"],
        "replay_arxiv_cursor": fetched["replay_arxiv_cursor"],
        "replay_stage": fetched["replay_stage"],
        "provider_total_count": fetched.get("provider_total_count"),
    }


async def analyze_author_publications(
    session: AsyncSession | None,
    *,
    authors: list[dict[str, Any]],
    limit: int = 20,
    cursor: str | None = None,
    filters: dict[str, Any] | None = None,
    sort_by: str | None = None,
    sort_direction: str | None = None,
    request_id: str | None = None,
) -> dict[str, Any]:
    total_started = time.perf_counter()
    page_limit = max(1, min(int(limit or 20), 20))
    cursor_payload = _decode_cursor(cursor)
    page_offset = 0
    stage = None
    oa_cursor = None
    arxiv_cursor = None
    if cursor_payload is not None:
        try:
            page_offset = max(0, int(cursor_payload.get("page_offset") or cursor_payload.get("offset") or 0))
        except (TypeError, ValueError):
            page_offset = 0
        stage = cursor_payload.get("stage") or None
        oa_cursor = cursor_payload.get("oa_cursor")
        arxiv_cursor = cursor_payload.get("arxiv_cursor")

    collected = await _collect_author_publications(
        session,
        authors=authors,
        persist=True,
        request_id=request_id,
        collect_all=False,
        stage=stage,
        oa_cursor=oa_cursor,
        arxiv_cursor=arxiv_cursor,
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
            "provider_total_count": None,
            "unsupported": True,
            "unsupported_reason": collected.get("unsupported_reason"),
        }

    normalized_filters = normalize_filters(filters)
    active_filters_key = build_filters_key(normalized_filters)
    active_sort_key = publication_sort_key(sort_by, sort_direction)
    authors_key = collected["authors_key"]
    records_key = collected["records_key"]

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
        if not filters_key_matches(cursor_payload.get("filters_key", ""), active_filters_key):
            raise AuthorAnalysisError(
                "Pagination cursor does not match the active filters.",
                status_code=422,
            )
        if cursor_payload.get("sort_key", "-") != active_sort_key:
            raise AuthorAnalysisError(
                "Pagination cursor does not match the active sort.",
                status_code=422,
            )

    enrich_started = time.perf_counter()
    all_items = await enrich_publication_items_authors(session, collected["items"])
    _log_stage(rid, "enrich_authors", enrich_started, items=len(all_items))
    facet_started = time.perf_counter()
    facets = build_dependent_publication_facets(all_items, normalized_filters)
    filtered_items = apply_publication_filters(all_items, normalized_filters)
    timeline = build_publication_timeline(filtered_items)
    sorted_items = sort_publications(
        filtered_items,
        sort_by=sort_by,
        sort_direction=sort_direction,
    )
    _log_stage(
        rid,
        "filter_facet_sort",
        facet_started,
        collected=len(all_items),
        filtered=len(filtered_items),
        page=len(sorted_items[page_offset : page_offset + page_limit]),
    )

    page_items = sorted_items[page_offset : page_offset + page_limit]
    next_offset = page_offset + len(page_items)
    remaining_in_page = next_offset < len(sorted_items)
    provider_has_more = bool(collected.get("provider_has_more"))
    has_more = remaining_in_page or provider_has_more
    next_cursor = None
    if has_more:
        if remaining_in_page:
            next_stage = collected.get("replay_stage") or stage or "openalex"
            next_oa = collected.get("replay_oa_cursor")
            next_arxiv = collected.get("replay_arxiv_cursor")
            encoded_offset = next_offset
        else:
            next_stage = collected.get("next_stage") or "done"
            next_oa = collected.get("next_oa_cursor")
            next_arxiv = collected.get("next_arxiv_cursor")
            encoded_offset = 0
        if next_stage != "done" or remaining_in_page:
            next_cursor = _encode_cursor(
                {
                    "v": 3,
                    "mode": mode,
                    "authors_key": authors_key,
                    "records_key": records_key,
                    "filters_key": active_filters_key,
                    "sort_key": active_sort_key,
                    "stage": next_stage,
                    "oa_cursor": next_oa,
                    "arxiv_cursor": next_arxiv,
                    "page_offset": encoded_offset,
                    "limit": page_limit,
                }
            )
        else:
            has_more = False

    persistence = collected.get("persistence")
    if persistence is not None and session is not None:
        try:
            commit_started = time.perf_counter()
            await session.commit()
            _log_stage(rid, "persistence_commit", commit_started, items=len(all_items))
            logger.info("analysis_req=%s persistence commit ok items=%s", rid, len(all_items))
        except Exception:
            logger.exception("analysis_req=%s Failed to commit analysis work persistence", rid)
            await session.rollback()

    _log_stage(
        rid,
        "analyze_total",
        total_started,
        returned=len(page_items),
        has_more=has_more,
    )
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
        "provider_total_count": collected.get("provider_total_count"),
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
    items = await enrich_publication_items_authors(session, collected["items"])
    return search_venue_facets(items, query, limit=limit)


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
    items = await enrich_publication_items_authors(session, collected["items"])
    return search_grant_facets(items, query, limit=limit)


async def build_author_publication_facets(
    session: AsyncSession | None,
    *,
    authors: list[dict[str, Any]],
    filters: dict[str, Any] | None = None,
) -> dict[str, Any]:
    started = time.perf_counter()
    collected = await _collect_author_publications(
        session,
        authors=authors,
        persist=False,
    )
    rid = collected.get("request_id") or "-"
    if collected.get("unsupported"):
        return {"sources": [], "institutions": [], "venues": [], "grants": [], "authors": []}
    enrich_started = time.perf_counter()
    items = await enrich_publication_items_authors(session, collected["items"])
    _log_stage(rid, "facets_enrich_authors", enrich_started, items=len(items))
    facets = build_dependent_publication_facets(items, filters)
    _log_stage(
        rid,
        "facets_total",
        started,
        items=len(items),
        sources=len(facets.get("sources") or []),
        institutions=len(facets.get("institutions") or []),
        venues=len(facets.get("venues") or []),
        grants=len(facets.get("grants") or []),
        authors=len(facets.get("authors") or []),
    )
    return facets
