"""Read-only author insights aggregation over stored canonical data."""

from __future__ import annotations

import base64
import itertools
import json
import logging
import re
import time
import uuid
from collections import Counter
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import (
    CanonicalAuthorInstitution,
    CanonicalAuthor,
    CanonicalWork,
    ProviderWorkRecord,
    WorkAuthorship,
    WorkGrantMatch,
)
from app.core.config import get_settings
from app.core.issn import compact_issn, extract_issns_from_work_metadata, format_issn
from app.services.analysis.author_publications import AuthorAnalysisError
from app.services.analysis.publication_filters import (
    apply_publication_filters,
    build_dependent_publication_facets,
    filters_key as build_filters_key,
    normalize_filters,
    normalize_venue_key,
    publication_venue,
)
from app.services.journal_metrics.service import JournalMetricsService, metrics_payload

logger = logging.getLogger(__name__)

InsightsProgressCallback = Callable[[str, int], Awaitable[None]]

EXHAUSTIVE_COMBINATION_AUTHOR_LIMIT = 6
COMBINATION_MODE_ALL = "all_combinations"
COMBINATION_MODE_SCALABLE = "scalable"

MAX_INSTITUTION_PARTNERSHIPS = 20
# Network preview "All" mode needs the full paired-institution set.
MAX_INSTITUTION_NETWORK_NODES = 250


def log_insights_timing(phase: str, started: float, **fields: Any) -> float:
    """Log a Collaboration Insights phase duration in milliseconds."""
    elapsed_ms = (time.perf_counter() - started) * 1000
    extra = "".join(f" {key}={value}" for key, value in fields.items())
    logger.info(
        "author_insights_timing phase=%s elapsed_ms=%.2f%s",
        phase,
        elapsed_ms,
        extra,
    )
    return elapsed_ms


@dataclass(frozen=True)
class SelectedAuthor:
    canonical_author_id: str
    display_name: str


@dataclass(frozen=True)
class InstitutionRef:
    key: str
    id: str
    name: str
    country: str | None = None

    def as_response(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "country": self.country,
        }


@dataclass
class StoredWorkInsights:
    id: str
    title: str
    publication_year: int | None
    providers: list[str] = field(default_factory=list)
    source: str | None = None
    journal: str | None = None
    citation_count: int | None = None
    grants: list[dict[str, Any]] = field(default_factory=list)
    authors: list[dict[str, Any]] = field(default_factory=list)
    institutions: dict[str, InstitutionRef] = field(default_factory=dict)
    source_records: list[dict[str, str]] = field(default_factory=list)
    doi: str | None = None
    url: str | None = None
    openalex_id: str | None = None
    source_id: str | None = None
    arxiv_id: str | None = None
    authorship_count: int = 0
    authorship_with_institution_count: int = 0
    issns: list[str] = field(default_factory=list)

    def as_filter_item(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "title": self.title,
            "publication_year": self.publication_year,
            "providers": self.providers,
            "source": self.source,
            "journal": self.journal,
            "citation_count": self.citation_count,
            "cited_by_count": self.citation_count,
            "grants": self.grants,
            "authors": self.authors,
        }

    def as_publication_item(self) -> dict[str, Any]:
        provider = self.source or (self.providers[0] if self.providers else "stored")
        return {
            "id": self.id,
            "result_id": self.id,
            "canonical_work_id": self.id,
            "result_type": "work",
            "title": self.title,
            "authors": self.authors,
            "publication_year": self.publication_year,
            "journal": self.journal,
            "primary_source": self.journal,
            "citation_count": self.citation_count,
            "cited_by_count": self.citation_count,
            "doi": self.doi,
            "url": self.url,
            "providers": self.providers,
            "grants": self.grants,
            "analysis_match": {
                "verified": True,
                "method": "stored_author_insights_combination",
            },
            "source": provider,
            "openalex_id": self.openalex_id,
            "source_id": self.source_id,
            "source_records": self.source_records,
        }

    @property
    def institution_keys(self) -> set[str]:
        return set(self.institutions.keys())


def stable_author_combination_id(author_ids: list[str] | tuple[str, ...]) -> str:
    """Stable provider-independent ID for a selected author subset."""
    return "+".join(sorted(str(author_id) for author_id in author_ids))


def build_author_combinations(
    authors: list[SelectedAuthor],
) -> list[tuple[str, tuple[SelectedAuthor, ...]]]:
    """Return all selected-author combinations of size 2+."""
    if len(authors) < 2:
        return []

    by_id = sorted(authors, key=lambda author: author.canonical_author_id)
    combinations: list[tuple[str, tuple[SelectedAuthor, ...]]] = []
    for size in range(2, len(by_id) + 1):
        for group in itertools.combinations(by_id, size):
            combo_id = stable_author_combination_id(
                [author.canonical_author_id for author in group]
            )
            combinations.append((combo_id, group))
    return combinations


def build_scalable_author_combinations(
    authors: list[SelectedAuthor],
    membership: dict[str, set[str]],
) -> list[tuple[str, tuple[SelectedAuthor, ...]]]:
    """Pairwise + all-selected + observed higher-order groups; never 2^N subsets."""
    if len(authors) < 2:
        return []

    authors_by_id = {author.canonical_author_id: author for author in authors}
    ordered = sorted(authors, key=lambda author: author.canonical_author_id)
    combinations: dict[str, tuple[SelectedAuthor, ...]] = {}

    for left, right in itertools.combinations(ordered, 2):
        combo_id = stable_author_combination_id(
            [left.canonical_author_id, right.canonical_author_id]
        )
        combinations[combo_id] = (left, right)

    all_selected_id = stable_author_combination_id(
        [author.canonical_author_id for author in ordered]
    )
    combinations[all_selected_id] = tuple(ordered)

    for author_ids in membership.values():
        selected_ids = sorted(
            author_id for author_id in author_ids if author_id in authors_by_id
        )
        if len(selected_ids) < 3:
            continue
        combo_id = stable_author_combination_id(selected_ids)
        if combo_id in combinations:
            continue
        combinations[combo_id] = tuple(authors_by_id[author_id] for author_id in selected_ids)

    return list(combinations.items())


def build_insights_combinations(
    authors: list[SelectedAuthor],
    membership: dict[str, set[str]] | None = None,
) -> tuple[str, list[tuple[str, tuple[SelectedAuthor, ...]]]]:
    if len(authors) <= EXHAUSTIVE_COMBINATION_AUTHOR_LIMIT:
        return COMBINATION_MODE_ALL, build_author_combinations(authors)
    return COMBINATION_MODE_SCALABLE, build_scalable_author_combinations(
        authors,
        membership or {},
    )


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


def _normalize_excluded_work_ids(values: list[str] | None) -> set[str]:
    excluded: set[str] = set()
    for value in values or []:
        text = str(value or "").strip()
        if not text:
            continue
        try:
            excluded.add(str(uuid.UUID(text)))
        except (TypeError, ValueError):
            continue
    return excluded


class AuthorInsightsService:
    """Build dashboard-ready insights from already persisted canonical records.

    This service intentionally does not call OpenAlex/arXiv and does not resolve or
    re-persist works. Missing provider metadata remains missing until existing
    ingestion/persistence flows store it.
    """

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def build_dashboard(
        self,
        *,
        authors: list[dict[str, Any]],
        filters: dict[str, Any] | None = None,
        excluded_work_ids: list[str] | None = None,
        on_progress: InsightsProgressCallback | None = None,
    ) -> dict[str, Any]:
        started = time.perf_counter()

        async def _progress(stage: str, percent: int) -> None:
            if on_progress is not None:
                await on_progress(stage, percent)

        await _progress("Preparing", 5)
        selected_authors = await self._resolve_selected_authors(authors)
        selected_ids = [author.canonical_author_id for author in selected_authors]

        await _progress("Loading publications", 20)

        load_started = time.perf_counter()
        work_membership = await self._load_work_membership(selected_ids)
        stored_works = await self._load_stored_work_insights(set(work_membership.keys()))
        excluded_set = _normalize_excluded_work_ids(excluded_work_ids)
        if excluded_set:
            work_membership = {
                work_id: author_ids
                for work_id, author_ids in work_membership.items()
                if work_id not in excluded_set
            }
            stored_works = {
                work_id: work
                for work_id, work in stored_works.items()
                if work_id not in excluded_set
            }

        normalized_filters = normalize_filters(filters)
        filter_items = [work.as_filter_item() for work in stored_works.values()]
        facets = build_dependent_publication_facets(filter_items, normalized_filters)
        logger.info(
            "insights_facets selected_ids=%s membership_works=%s stored_works=%s "
            "filter_items=%s sources=%s institutions=%s venues=%s grants=%s authors=%s "
            "provider_calls=openalex:0,arxiv:0,orcid:0,scopus:0",
            selected_ids,
            len(work_membership),
            len(stored_works),
            len(filter_items),
            len(facets.get("sources") or []),
            len(facets.get("institutions") or []),
            len(facets.get("venues") or []),
            len(facets.get("grants") or []),
            len(facets.get("authors") or []),
        )
        filtered_items = apply_publication_filters(filter_items, normalized_filters)
        filtered_work_ids = {str(item["id"]) for item in filtered_items}

        filtered_works = {
            work_id: work
            for work_id, work in stored_works.items()
            if work_id in filtered_work_ids
        }
        filtered_membership = {
            work_id: author_ids
            for work_id, author_ids in work_membership.items()
            if work_id in filtered_work_ids
        }
        log_insights_timing(
            "publication_work_loading",
            load_started,
            work_count=len(filtered_works),
            selected_author_count=len(selected_authors),
        )

        await _progress("Calculating collaboration metrics", 45)
        collab_started = time.perf_counter()
        combination_mode, combinations = build_insights_combinations(
            selected_authors,
            filtered_membership,
        )
        combination_rows = self._build_combination_rows(
            combinations=combinations,
            works=filtered_works,
            membership=filtered_membership,
        )
        self._log_membership_diagnostics(
            selected_authors=selected_authors,
            raw_membership=work_membership,
            filtered_membership=filtered_membership,
            combination_rows=combination_rows,
        )
        metrics = self._build_metrics(
            selected_count=len(selected_authors),
            works=filtered_works,
            membership=filtered_membership,
        )
        collaboration_by_year = self._build_collaboration_by_year(
            selected_count=len(selected_authors),
            works=filtered_works,
            membership=filtered_membership,
        )
        participation = self._build_participation(
            works=filtered_works,
            membership=filtered_membership,
        )
        log_insights_timing(
            "collaboration_aggregation",
            collab_started,
            combination_count=len(combination_rows),
            combination_mode=combination_mode,
            work_count=len(filtered_works),
        )

        selected_author_names_by_id = {
            author.canonical_author_id: author.display_name for author in selected_authors
        }
        await _progress("Calculating institutions/citations", 65)
        institution_started = time.perf_counter()
        citation_activity = self._build_citation_activity(filtered_works)
        institution_partnerships, institution_network = self._build_institution_aggregates(
            works=filtered_works,
            membership=filtered_membership,
            selected_author_names_by_id=selected_author_names_by_id,
        )
        institution_data_quality = self._build_institution_data_quality(filtered_works)
        log_insights_timing(
            "institution_aggregation",
            institution_started,
            partnership_count=len(institution_partnerships),
            network_node_count=len(institution_network.get("nodes") or []),
        )

        await _progress("Loading journal metrics", 80)
        journal_started = time.perf_counter()
        top_journals = await self._build_top_journals(filtered_works)
        log_insights_timing(
            "journal_metrics",
            journal_started,
            venue_count=len(top_journals),
        )

        await _progress("Finalizing", 95)
        result = {
            "authors": [
                {
                    "canonical_author_id": author.canonical_author_id,
                    "display_name": author.display_name,
                }
                for author in selected_authors
            ],
            "metrics": metrics,
            "combinations": combination_rows,
            "combination_mode": combination_mode,
            "collaboration_by_year": collaboration_by_year,
            "participation": participation,
            "institution_network": institution_network,
            "institution_partnerships": institution_partnerships,
            "citation_activity": citation_activity,
            "top_journals": top_journals,
            "default_combination_id": self._default_combination_id(combination_rows),
            "institution_data_quality": institution_data_quality,
            "facets": facets,
        }
        log_insights_timing(
            "dashboard_total",
            started,
            work_count=len(filtered_works),
            selected_author_count=len(selected_authors),
        )
        return result

    async def build_combination_publications(
        self,
        *,
        authors: list[dict[str, Any]],
        combination_id: str,
        filters: dict[str, Any] | None = None,
        excluded_work_ids: list[str] | None = None,
        cursor: str | None = None,
        limit: int = 20,
    ) -> dict[str, Any]:
        started = time.perf_counter()
        selected_authors = await self._resolve_selected_authors(authors)
        selected_ids = [author.canonical_author_id for author in selected_authors]
        selected_set = set(selected_ids)
        combination_author_ids = self._resolve_combination_author_ids(
            combination_id,
            selected_set=selected_set,
        )

        work_membership = await self._load_work_membership(selected_ids)
        matching_work_ids = {
            work_id
            for work_id, author_ids in work_membership.items()
            if combination_author_ids.issubset(author_ids)
        }
        excluded_set = _normalize_excluded_work_ids(excluded_work_ids)
        if excluded_set:
            matching_work_ids.difference_update(excluded_set)
        stored_works = await self._load_stored_work_insights(matching_work_ids)

        normalized_filters = normalize_filters(filters)
        active_filters_key = build_filters_key(normalized_filters)
        request_key = self._drilldown_request_key(
            selected_author_ids=selected_ids,
            combination_id=combination_id,
            filters_key=active_filters_key,
        )
        page_limit = max(1, min(int(limit or 20), 20))
        offset = 0

        cursor_payload = _decode_cursor(cursor)
        if cursor_payload is not None:
            if cursor_payload.get("request_key") != request_key:
                raise AuthorAnalysisError(
                    "Pagination cursor does not match the selected author combination.",
                    status_code=422,
                )
            try:
                offset = max(0, int(cursor_payload.get("offset") or 0))
            except (TypeError, ValueError):
                offset = 0
        elif cursor not in (None, "", "*"):
            raise AuthorAnalysisError("Invalid pagination cursor.", status_code=422)

        filter_items = [work.as_filter_item() for work in stored_works.values()]
        filtered_items = apply_publication_filters(filter_items, normalized_filters)
        filtered_work_ids = {str(item["id"]) for item in filtered_items}
        filtered_works = [
            work
            for work in stored_works.values()
            if work.id in filtered_work_ids
        ]
        filtered_works.sort(
            key=lambda work: (
                -(work.publication_year or 0),
                -(work.citation_count or 0),
                work.title.lower(),
                work.id,
            )
        )

        page_works = filtered_works[offset : offset + page_limit]
        next_offset = offset + len(page_works)
        has_more = next_offset < len(filtered_works)
        next_cursor = None
        if has_more:
            next_cursor = _encode_cursor(
                {
                    "v": 1,
                    "request_key": request_key,
                    "offset": next_offset,
                    "limit": page_limit,
                }
            )

        result = {
            "combination_id": combination_id,
            "items": [work.as_publication_item() for work in page_works],
            "pagination": {
                "next_cursor": next_cursor,
                "has_more": bool(next_cursor),
            },
        }
        logger.info(
            "author_insights_drilldown_ms=%.2f work_count=%s selected_author_count=%s",
            (time.perf_counter() - started) * 1000,
            len(filtered_works),
            len(selected_authors),
        )
        return result

    def _resolve_combination_author_ids(
        self,
        combination_id: str,
        *,
        selected_set: set[str],
    ) -> set[str]:
        raw_parts = [part.strip() for part in str(combination_id or "").split("+")]
        parts: list[str] = []
        for part in raw_parts:
            if not part:
                continue
            try:
                author_id = str(uuid.UUID(part))
            except (TypeError, ValueError):
                raise AuthorAnalysisError(
                    "Invalid author combination ID.",
                    status_code=400,
                ) from None
            if author_id not in parts:
                parts.append(author_id)
        if len(parts) < 1:
            raise AuthorAnalysisError(
                "Author combination must include at least one selected author.",
                status_code=400,
            )
        if not set(parts).issubset(selected_set):
            raise AuthorAnalysisError(
                "Author combination is not part of the selected authors.",
                status_code=404,
            )
        if stable_author_combination_id(parts) != combination_id:
            raise AuthorAnalysisError(
                "Invalid author combination ID.",
                status_code=400,
            )
        return set(parts)

    def _drilldown_request_key(
        self,
        *,
        selected_author_ids: list[str],
        combination_id: str,
        filters_key: str,
    ) -> str:
        return "|".join(
            [
                ",".join(sorted(selected_author_ids)),
                combination_id,
                filters_key,
            ]
        )

    async def _resolve_selected_authors(
        self,
        raw_authors: list[dict[str, Any]],
    ) -> list[SelectedAuthor]:
        ordered_ids: list[uuid.UUID] = []
        requested_names: dict[str, str] = {}
        seen: set[str] = set()
        for row in raw_authors:
            raw_id = str(row.get("canonical_author_id") or "").strip()
            try:
                canonical_uuid = uuid.UUID(raw_id)
            except (TypeError, ValueError):
                raise AuthorAnalysisError(
                    f"Invalid canonical author ID: {raw_id or '<empty>'}",
                    status_code=422,
                ) from None
            key = str(canonical_uuid)
            if key in seen:
                continue
            seen.add(key)
            ordered_ids.append(canonical_uuid)
            display_name = " ".join(str(row.get("display_name") or "").split())
            if display_name:
                requested_names[key] = display_name

        if not ordered_ids:
            raise AuthorAnalysisError("At least one author is required.", status_code=422)

        result = await self.session.execute(
            select(CanonicalAuthor).where(CanonicalAuthor.id.in_(ordered_ids))
        )
        rows = {str(author.id): author for author in result.scalars().all()}
        missing = [str(author_id) for author_id in ordered_ids if str(author_id) not in rows]
        if missing:
            raise AuthorAnalysisError(
                f"Canonical author not found: {missing[0]}",
                status_code=404,
            )

        selected: list[SelectedAuthor] = []
        for author_id in ordered_ids:
            key = str(author_id)
            author = rows[key]
            selected.append(
                SelectedAuthor(
                    canonical_author_id=key,
                    display_name=author.preferred_name or requested_names.get(key) or key,
                )
            )
        return selected

    async def _load_work_membership(
        self,
        selected_author_ids: list[str],
    ) -> dict[str, set[str]]:
        selected_uuids = [uuid.UUID(author_id) for author_id in selected_author_ids]
        selected_set = {str(author_id) for author_id in selected_uuids}
        membership: dict[str, set[str]] = {}

        authorship_result = await self.session.execute(
            select(
                WorkAuthorship.canonical_work_id,
                WorkAuthorship.canonical_author_id,
            ).where(WorkAuthorship.canonical_author_id.in_(selected_uuids))
        )
        for work_id, author_id in authorship_result.all():
            if author_id is None:
                continue
            author_key = str(author_id)
            if author_key not in selected_set:
                continue
            membership.setdefault(str(work_id), set()).add(author_key)

        return membership

    async def _load_stored_work_insights(
        self,
        work_ids: set[str],
    ) -> dict[str, StoredWorkInsights]:
        if not work_ids:
            return {}

        work_uuids = [uuid.UUID(work_id) for work_id in sorted(work_ids)]
        works_result = await self.session.execute(
            select(CanonicalWork).where(CanonicalWork.id.in_(work_uuids))
        )
        works = {
            str(work.id): StoredWorkInsights(
                id=str(work.id),
                title=work.title,
                publication_year=work.publication_year,
                doi=work.doi,
                arxiv_id=work.arxiv_id,
            )
            for work in works_result.scalars().all()
        }

        provider_result = await self.session.execute(
            select(ProviderWorkRecord).where(
                ProviderWorkRecord.canonical_work_id.in_(work_uuids)
            )
        )
        for record in provider_result.scalars().all():
            work = works.get(str(record.canonical_work_id))
            if work is None:
                continue
            if record.provider not in work.providers:
                work.providers.append(record.provider)
            if work.source is None:
                work.source = record.provider
            work.source_records.append(
                {
                    "provider": record.provider,
                    "provider_work_id": record.provider_work_id,
                }
            )
            if record.provider == "openalex" and work.openalex_id is None:
                work.openalex_id = record.provider_work_id
            if record.provider == "arxiv" and work.arxiv_id is None:
                work.arxiv_id = record.provider_work_id
            if work.source_id is None:
                work.source_id = record.provider_work_id
            raw = record.raw_metadata if isinstance(record.raw_metadata, dict) else {}
            citation_count = _extract_citation_count(raw)
            if citation_count is not None:
                work.citation_count = (
                    citation_count
                    if work.citation_count is None
                    else max(work.citation_count, citation_count)
                )
            if work.journal is None:
                work.journal = _extract_venue(raw)
            for compact in extract_issns_from_work_metadata(raw):
                if compact not in work.issns:
                    work.issns.append(compact)
            if work.publication_year is None:
                work.publication_year = _extract_publication_year(raw)
            if work.doi is None:
                work.doi = _extract_doi(raw)
            if work.url is None:
                work.url = _extract_url(raw)

        grant_result = await self.session.execute(
            select(WorkGrantMatch).where(WorkGrantMatch.canonical_work_id.in_(work_uuids))
        )
        for grant in grant_result.scalars().all():
            work = works.get(str(grant.canonical_work_id))
            if work is None:
                continue
            work.grants.append(
                {
                    "award_id": grant.grant_number,
                    "funder_name": _extract_funder_name(grant.raw_metadata),
                    "verified": grant.verified,
                    "match_type": grant.match_type,
                    "provider": grant.provider,
                }
            )

        authorship_result = await self.session.execute(
            select(WorkAuthorship).where(WorkAuthorship.canonical_work_id.in_(work_uuids))
        )
        authorships = authorship_result.scalars().all()
        profile_institutions = await self._load_profile_institution_fallbacks(
            {
                authorship.canonical_author_id
                for authorship in authorships
                if authorship.canonical_author_id is not None
            }
        )
        for authorship in authorships:
            work = works.get(str(authorship.canonical_work_id))
            if work is None:
                continue
            work.authorship_count += 1
            institutions = _resolve_authorship_institutions(
                authorship,
                profile_institutions=profile_institutions,
            )
            if institutions:
                work.authorship_with_institution_count += 1
            for institution in institutions:
                existing = work.institutions.get(institution.key)
                work.institutions[institution.key] = _merge_institution_refs(
                    existing,
                    institution,
                )
            work.authors.append(_serialize_work_author(authorship))

        for work in works.values():
            work.providers = sorted(work.providers)
            work.source_records = sorted(
                work.source_records,
                key=lambda row: (
                    str(row.get("provider") or ""),
                    str(row.get("provider_work_id") or ""),
                ),
            )
            work.authors = sorted(
                work.authors,
                key=lambda row: int(row.get("author_position") or 0),
            )
            work.grants = sorted(
                work.grants,
                key=lambda row: (
                    str(row.get("provider") or ""),
                    str(row.get("award_id") or ""),
                ),
            )
        return works

    async def _load_profile_institution_fallbacks(
        self,
        author_ids: set[uuid.UUID],
    ) -> dict[str, list[InstitutionRef]]:
        if not author_ids:
            return {}
        result = await self.session.execute(
            select(CanonicalAuthorInstitution).where(
                CanonicalAuthorInstitution.canonical_author_id.in_(author_ids)
            )
        )
        rows_by_author: dict[str, list[CanonicalAuthorInstitution]] = {}
        for row in result.scalars().all():
            rows_by_author.setdefault(str(row.canonical_author_id), []).append(row)

        fallback: dict[str, list[InstitutionRef]] = {}
        for author_id, rows in rows_by_author.items():
            current_rows = [row for row in rows if row.is_current]
            candidates = current_rows or rows
            latest_year = max(
                (
                    row.valid_to_year
                    or row.valid_from_year
                    or 0
                    for row in candidates
                ),
                default=0,
            )
            selected_rows = [
                row
                for row in candidates
                if (row.valid_to_year or row.valid_from_year or 0) == latest_year
            ] or candidates
            refs: dict[str, InstitutionRef] = {}
            for row in selected_rows:
                ref = normalize_institution(
                    {
                        "id": row.institution_id,
                        "name": row.institution_name,
                        "country_code": row.country_code,
                    }
                )
                if ref is not None:
                    refs[ref.key] = _merge_institution_refs(refs.get(ref.key), ref)
            if refs:
                fallback[author_id] = list(refs.values())
        return fallback

    def _build_metrics(
        self,
        *,
        selected_count: int,
        works: dict[str, StoredWorkInsights],
        membership: dict[str, set[str]],
    ) -> dict[str, Any]:
        total_unique = len(works)
        multi_selected = sum(1 for author_ids in membership.values() if len(author_ids) >= 2)
        all_selected = sum(
            1 for author_ids in membership.values() if len(author_ids) == selected_count
        )
        multi_institution = sum(
            1 for work in works.values() if len(work.institution_keys) >= 2
        )
        citation_values = [
            work.citation_count for work in works.values() if work.citation_count is not None
        ]
        total_citations = sum(citation_values)
        average = total_citations / len(citation_values) if citation_values else 0
        return {
            "total_unique_publications": total_unique,
            "multi_selected_author_publications": multi_selected,
            "all_selected_author_publications": all_selected,
            "multi_institution_publications": multi_institution,
            "total_citations": total_citations,
            "average_citations": round(average, 2),
        }

    def _build_combination_rows(
        self,
        *,
        combinations: list[tuple[str, tuple[SelectedAuthor, ...]]],
        works: dict[str, StoredWorkInsights],
        membership: dict[str, set[str]],
    ) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        for combo_id, authors in combinations:
            combo_author_ids = {author.canonical_author_id for author in authors}
            display_authors = sorted(
                authors,
                key=lambda author: (
                    author.display_name.lower(),
                    author.canonical_author_id,
                ),
            )
            matching_work_ids = [
                work_id
                for work_id, author_ids in membership.items()
                if combo_author_ids.issubset(author_ids)
            ]
            institution_keys: set[str] = set()
            grant_keys: set[str] = set()
            citation_count = 0
            citation_value_count = 0
            for work_id in matching_work_ids:
                work = works.get(work_id)
                if work is None:
                    continue
                if work.citation_count is not None:
                    citation_count += work.citation_count
                    citation_value_count += 1
                institution_keys.update(work.institution_keys)
                for grant in work.grants:
                    key = (
                        str(grant.get("provider") or ""),
                        str(grant.get("award_id") or ""),
                    )
                    if key[1]:
                        grant_keys.add(key)
            author_names = [author.display_name for author in display_authors]
            rows.append(
                {
                    "id": combo_id,
                    "author_ids": [
                        author.canonical_author_id for author in display_authors
                    ],
                    "author_names": author_names,
                    "label": " + ".join(author_names),
                    "publication_count": len(matching_work_ids),
                    "citation_count": citation_count,
                    "average_citations": round(
                        citation_count / citation_value_count, 2
                    )
                    if citation_value_count
                    else 0,
                    "institution_count": len(institution_keys),
                    "grant_count": len(grant_keys),
                }
            )
        return sorted(
            rows,
            key=lambda row: (
                len(row["author_ids"]),
                -int(row["publication_count"]),
                row["label"].lower(),
            ),
        )

    def _log_membership_diagnostics(
        self,
        *,
        selected_authors: list[SelectedAuthor],
        raw_membership: dict[str, set[str]],
        filtered_membership: dict[str, set[str]],
        combination_rows: list[dict[str, Any]],
    ) -> None:
        selected_ids = [author.canonical_author_id for author in selected_authors]
        selected_set = set(selected_ids)
        author_work_counts = [
            {
                "author_id": author.canonical_author_id,
                "author_name": author.display_name,
                "stored_work_count": sum(
                    1
                    for author_ids in raw_membership.values()
                    if author.canonical_author_id in author_ids
                ),
            }
            for author in selected_authors
        ]
        bucket_counts: dict[str, int] = {}
        for author_ids in filtered_membership.values():
            matching_ids = sorted(selected_set.intersection(author_ids))
            label = "+".join(
                author.display_name
                for author in selected_authors
                if author.canonical_author_id in matching_ids
            )
            if label:
                bucket_counts[label] = bucket_counts.get(label, 0) + 1
        all_selected_count = sum(
            1 for author_ids in raw_membership.values() if selected_set.issubset(author_ids)
        )
        logger.info(
            "author_insights_membership_diagnostics authors=%s union_work_count=%s "
            "filtered_union_work_count=%s all_selected_intersection_count=%s "
            "filtered_bucket_counts=%s combination_counts=%s",
            author_work_counts,
            len(raw_membership),
            len(filtered_membership),
            all_selected_count,
            bucket_counts,
            [
                {
                    "id": row.get("id"),
                    "label": row.get("label"),
                    "publication_count": row.get("publication_count"),
                }
                for row in combination_rows
            ],
        )

    def _build_collaboration_by_year(
        self,
        *,
        selected_count: int,
        works: dict[str, StoredWorkInsights],
        membership: dict[str, set[str]],
    ) -> list[dict[str, Any]]:
        collaborative_counts: dict[int, int] = {}
        year_totals: dict[int, int] = {}
        for work in works.values():
            if work.publication_year is not None:
                year_totals[work.publication_year] = (
                    year_totals.get(work.publication_year, 0) + 1
                )
        for work_id, author_ids in membership.items():
            if selected_count > 1 and len(author_ids) < 2:
                continue
            year = works.get(work_id).publication_year if works.get(work_id) else None
            if year is None:
                continue
            collaborative_counts[year] = collaborative_counts.get(year, 0) + 1
        return [
            {
                "year": year,
                "publication_count": collaborative_counts[year],
                "percentage_of_year_total": round(
                    (collaborative_counts[year] / year_totals.get(year, 1)) * 100,
                    2,
                ),
            }
            for year in sorted(collaborative_counts.keys())
        ]

    def _build_participation(
        self,
        *,
        works: dict[str, StoredWorkInsights],
        membership: dict[str, set[str]],
    ) -> dict[str, Any]:
        selected_counts: dict[int, int] = {}
        institution_counts: dict[int, int] = {}
        for work_id, author_ids in membership.items():
            selected_count = len(author_ids)
            selected_counts[selected_count] = selected_counts.get(selected_count, 0) + 1
            institution_count = len(works[work_id].institution_keys) if work_id in works else 0
            if institution_count > 0:
                institution_counts[institution_count] = (
                    institution_counts.get(institution_count, 0) + 1
                )

        return {
            "selected_author_counts": [
                {"selected_author_count": count, "publication_count": selected_counts[count]}
                for count in sorted(selected_counts.keys())
            ],
            "institution_counts": [
                {
                    "institution_count": count,
                    "publication_count": institution_counts[count],
                }
                for count in sorted(institution_counts.keys())
            ],
        }

    def _build_institution_aggregates(
        self,
        *,
        works: dict[str, StoredWorkInsights],
        membership: dict[str, set[str]],
        selected_author_names_by_id: dict[str, str],
    ) -> tuple[list[dict[str, Any]], dict[str, list[dict[str, Any]]]]:
        pair_map: dict[tuple[str, str], dict[str, Any]] = {}
        node_work_ids: dict[str, set[str]] = {}
        institution_by_key: dict[str, InstitutionRef] = {}

        for work_id, work in works.items():
            institutions = sorted(
                work.institutions.values(),
                key=lambda ref: (ref.name.lower(), ref.id),
            )
            for institution in institutions:
                institution_by_key[institution.key] = _merge_institution_refs(
                    institution_by_key.get(institution.key),
                    institution,
                )
                node_work_ids.setdefault(institution.key, set()).add(work_id)

            if len(institutions) < 2:
                continue

            selected_author_ids = membership.get(work_id, set())
            for left, right in itertools.combinations(institutions, 2):
                pair_key = tuple(sorted([left.key, right.key]))
                row = pair_map.setdefault(
                    pair_key,
                    {
                        "institution_a": institution_by_key.get(pair_key[0])
                        or (left if left.key == pair_key[0] else right),
                        "institution_b": institution_by_key.get(pair_key[1])
                        or (right if right.key == pair_key[1] else left),
                        "work_ids": set(),
                        "selected_author_ids": set(),
                    },
                )
                row["institution_a"] = _merge_institution_refs(
                    row["institution_a"],
                    institution_by_key[pair_key[0]],
                )
                row["institution_b"] = _merge_institution_refs(
                    row["institution_b"],
                    institution_by_key[pair_key[1]],
                )
                row["work_ids"].add(work_id)
                row["selected_author_ids"].update(selected_author_ids)

        partnership_rows = []
        for row in pair_map.values():
            selected_ids = sorted(
                row["selected_author_ids"],
                key=lambda author_id: (
                    selected_author_names_by_id.get(author_id, author_id).lower(),
                    author_id,
                ),
            )
            partnership_rows.append(
                {
                    "institution_a": row["institution_a"].as_response(),
                    "institution_b": row["institution_b"].as_response(),
                    "shared_publication_count": len(row["work_ids"]),
                    "selected_author_ids": selected_ids,
                    "selected_author_names": [
                        selected_author_names_by_id.get(author_id, author_id)
                        for author_id in selected_ids
                    ],
                }
            )

        partnership_rows = sorted(
            partnership_rows,
            key=lambda row: (
                -row["shared_publication_count"],
                row["institution_a"]["name"].lower(),
                row["institution_b"]["name"].lower(),
            ),
        )

        network = self._build_institution_network(
            pair_map=pair_map,
            node_work_ids=node_work_ids,
            institution_by_key=institution_by_key,
        )
        return partnership_rows[:MAX_INSTITUTION_PARTNERSHIPS], network

    def _build_institution_network(
        self,
        *,
        pair_map: dict[tuple[str, str], dict[str, Any]],
        node_work_ids: dict[str, set[str]],
        institution_by_key: dict[str, InstitutionRef],
    ) -> dict[str, list[dict[str, Any]]]:
        paired_keys = {key for pair in pair_map.keys() for key in pair}
        ranked_keys = sorted(
            paired_keys,
            key=lambda key: (
                -len(node_work_ids.get(key, set())),
                institution_by_key[key].name.lower(),
                institution_by_key[key].id,
            ),
        )[:MAX_INSTITUTION_NETWORK_NODES]
        retained = set(ranked_keys)

        nodes = [
            {
                **institution_by_key[key].as_response(),
                "publication_count": len(node_work_ids.get(key, set())),
            }
            for key in ranked_keys
        ]

        edges = []
        for pair_key, row in pair_map.items():
            if pair_key[0] not in retained or pair_key[1] not in retained:
                continue
            count = len(row["work_ids"])
            if count <= 0:
                continue
            left = institution_by_key[pair_key[0]]
            right = institution_by_key[pair_key[1]]
            edges.append(
                {
                    "source": left.id,
                    "target": right.id,
                    "shared_publication_count": count,
                }
            )
        edges.sort(
            key=lambda row: (
                -row["shared_publication_count"],
                row["source"],
                row["target"],
            )
        )
        return {"nodes": nodes, "edges": edges}

    def _build_institution_data_quality(
        self,
        works: dict[str, StoredWorkInsights],
    ) -> dict[str, int]:
        total = len(works)
        with_any = sum(1 for work in works.values() if work.institutions)
        without = total - with_any
        partial = sum(
            1
            for work in works.values()
            if work.authorship_count > 0
            and 0 < work.authorship_with_institution_count < work.authorship_count
        )
        complete = sum(
            1
            for work in works.values()
            if work.authorship_count > 0
            and work.authorship_with_institution_count == work.authorship_count
        )
        multi = sum(1 for work in works.values() if len(work.institutions) >= 2)
        return {
            "total_works": total,
            "works_with_any_institution": with_any,
            "works_without_institution": without,
            "works_with_partial_institution": partial,
            "works_with_complete_institution": complete,
            "works_with_multi_institution": multi,
        }

    def _build_citation_activity(
        self,
        works: dict[str, StoredWorkInsights],
    ) -> list[dict[str, Any]]:
        buckets: dict[int, dict[str, int]] = {}
        for work in works.values():
            if work.publication_year is None:
                continue
            bucket = buckets.setdefault(
                work.publication_year,
                {"citation_count": 0, "publication_count": 0},
            )
            bucket["citation_count"] += work.citation_count or 0
            bucket["publication_count"] += 1

        rows: list[dict[str, Any]] = []
        cumulative = 0
        for year in sorted(buckets.keys()):
            cumulative += buckets[year]["citation_count"]
            rows.append(
                {
                    "year": year,
                    "citation_count": buckets[year]["citation_count"],
                    "cumulative_citations": cumulative,
                    "publication_count": buckets[year]["publication_count"],
                }
            )
        return rows

    async def _build_top_journals(
        self,
        works: dict[str, StoredWorkInsights],
    ) -> list[dict[str, Any]]:
        counts: dict[str, int] = {}
        citation_counts: dict[str, int] = {}
        labels: dict[str, str] = {}
        issn_votes: dict[str, Counter[str]] = {}
        for work in works.values():
            item = work.as_filter_item()
            venue = publication_venue(item)
            if not venue:
                continue
            key = normalize_venue_key(venue)
            if not key:
                continue
            counts[key] = counts.get(key, 0) + 1
            citation_counts[key] = citation_counts.get(key, 0) + (work.citation_count or 0)
            labels[key] = _best_venue_label(labels.get(key), venue)
            if work.issns:
                votes = issn_votes.setdefault(key, Counter())
                votes.update(work.issns)

        ranked_keys = sorted(
            counts.keys(),
            key=lambda value: (-counts[value], labels[value].lower()),
        )[:10]
        rows: list[dict[str, Any]] = []
        issn_by_key: dict[str, str] = {}
        for key in ranked_keys:
            votes = issn_votes.get(key)
            compact = votes.most_common(1)[0][0] if votes else None
            if compact:
                issn_by_key[key] = compact
            rows.append(
                {
                    "venue": labels[key],
                    "publication_count": counts[key],
                    "citation_count": citation_counts[key],
                    "issn": format_issn(compact),
                    "journal_metrics": None,
                }
            )
        return await self._attach_journal_metrics(rows, issn_by_key)

    async def _attach_journal_metrics(
        self,
        rows: list[dict[str, Any]],
        issn_by_key: dict[str, str],
    ) -> list[dict[str, Any]]:
        unique_issns = list(dict.fromkeys(issn_by_key.values()))
        if not unique_issns:
            return rows
        names = {
            issn: next(
                (row["venue"] for row in rows if format_issn(issn) == row.get("issn")),
                None,
            )
            for issn in unique_issns
        }
        try:
            service = JournalMetricsService(self.session)
            cached = await service.enrich_issns(
                unique_issns,
                journal_names=names,
                timeout_seconds=get_settings().journal_metrics_enrichment_timeout_seconds,
            )
        except Exception:
            logger.warning("journal_metrics_insights_enrichment_failed", exc_info=True)
            return rows

        metrics_by_issn = {
            issn: metrics_payload(row) for issn, row in cached.items()
        }
        for row in rows:
            compact = compact_issn(row.get("issn"))
            if compact and compact in metrics_by_issn:
                row["journal_metrics"] = metrics_by_issn[compact]
        return rows

    def _default_combination_id(self, combinations: list[dict[str, Any]]) -> str | None:
        if not combinations:
            return None
        max_size = max(len(row.get("author_ids") or []) for row in combinations)
        all_selected = [
            row
            for row in combinations
            if len(row.get("author_ids") or []) == max_size
            and int(row.get("publication_count") or 0) > 0
        ]
        if all_selected:
            return str(sorted(all_selected, key=lambda row: str(row.get("id") or ""))[0]["id"])

        ranked = sorted(
            combinations,
            key=lambda row: (
                -int(row.get("publication_count") or 0),
                len(row.get("author_ids") or []),
                str(row.get("label") or "").lower(),
            ),
        )
        if int(ranked[0].get("publication_count") or 0) <= 0:
            return None
        return str(ranked[0]["id"])


def _extract_publication_year(raw: dict[str, Any]) -> int | None:
    for key in ("publication_year", "year"):
        value = raw.get(key)
        try:
            year = int(value) if value is not None else None
        except (TypeError, ValueError):
            year = None
        if year is not None and 1000 <= year <= 2100:
            return year
    for key in ("publication_date", "published_date"):
        value = str(raw.get(key) or "")
        if len(value) >= 4 and value[:4].isdigit():
            year = int(value[:4])
            if 1000 <= year <= 2100:
                return year
    return None


def _extract_citation_count(raw: dict[str, Any]) -> int | None:
    for key in ("citation_count", "cited_by_count"):
        value = raw.get(key)
        try:
            count = int(value) if value is not None else None
        except (TypeError, ValueError):
            count = None
        if count is not None and count >= 0:
            return count
    return None


def _extract_venue(raw: dict[str, Any]) -> str | None:
    for key in ("journal", "primary_source", "venue", "source_name"):
        value = raw.get(key)
        if value:
            text = " ".join(str(value).split())
            if text:
                return text
    primary_location = raw.get("primary_location")
    if isinstance(primary_location, dict):
        source = primary_location.get("source")
        if isinstance(source, dict):
            text = " ".join(str(source.get("display_name") or "").split())
            if text:
                return text
    return None


def _extract_doi(raw: dict[str, Any]) -> str | None:
    for key in ("doi", "DOI"):
        value = raw.get(key)
        if value:
            text = " ".join(str(value).split())
            if text:
                return text.replace("https://doi.org/", "").replace("http://doi.org/", "")
    return None


def _extract_url(raw: dict[str, Any]) -> str | None:
    for key in ("url", "entry_url", "pdf_url", "landing_page_url"):
        value = raw.get(key)
        if value:
            text = " ".join(str(value).split())
            if text:
                return text
    primary_location = raw.get("primary_location")
    if isinstance(primary_location, dict):
        for key in ("landing_page_url", "pdf_url"):
            value = primary_location.get(key)
            if value:
                text = " ".join(str(value).split())
                if text:
                    return text
    return None


def _serialize_work_author(authorship: WorkAuthorship) -> dict[str, Any]:
    raw = authorship.raw_metadata if isinstance(authorship.raw_metadata, dict) else {}
    provider_ids: dict[str, list[str]] = {"openalex": [], "orcid": [], "arxiv": []}
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
        "institutions": authorship.institutions or [],
        "institution_ids": authorship.institution_ids or [],
        "countries": authorship.countries or [],
        "author_position": authorship.author_position,
        "department": raw.get("department"),
        "raw_affiliation_text": raw.get("raw_affiliation_text"),
        "affiliation_source": raw.get("affiliation_source"),
        "affiliation_confidence": raw.get("affiliation_confidence"),
    }


def _extract_funder_name(raw: dict[str, Any] | None) -> str | None:
    if not isinstance(raw, dict):
        return None
    for key in ("funder_name", "funder_display_name", "funder"):
        value = raw.get(key)
        if value:
            text = " ".join(str(value).split())
            if text:
                return text
    return None


def _best_venue_label(existing: str | None, candidate: str) -> str:
    text = " ".join(str(candidate or "").split())
    if not text:
        return existing or text
    if not existing:
        return text

    def score(value: str) -> tuple[int, int, int]:
        letters = [char for char in value if char.isalpha()]
        uppercase = sum(1 for char in letters if char.isupper())
        all_lower = int(value == value.lower())
        return (0 if all_lower else 1, uppercase, len(value))

    return text if score(text) > score(existing) else existing


_INSTITUTION_PUNCT_RE = re.compile(r"[^\w\s]+", re.UNICODE)
_WHITESPACE_RE = re.compile(r"\s+")


def normalize_institution(raw: Any, *, country: str | None = None) -> InstitutionRef | None:
    if raw is None:
        return None

    if isinstance(raw, str):
        name = _clean_display_text(raw)
        provider_id = None
        country_code = _clean_country(country)
    elif isinstance(raw, dict):
        provider_id = _clean_institution_id(
            raw.get("id")
            or raw.get("institution_id")
            or raw.get("openalex_id")
        )
        name = _clean_display_text(
            raw.get("display_name")
            or raw.get("name")
            or raw.get("institution_name")
        )
        country_code = _clean_country(
            raw.get("country_code")
            or raw.get("country")
            or country
        )
    else:
        return None

    if provider_id:
        return InstitutionRef(
            key=f"id:{provider_id.lower()}",
            id=provider_id,
            name=name or provider_id,
            country=country_code,
        )

    normalized_name = _normalize_institution_name(name)
    if not normalized_name:
        return None
    country_key = (country_code or "").lower()
    key = f"name:{normalized_name}|country:{country_key}"
    return InstitutionRef(
        key=key,
        id=key,
        name=name or normalized_name,
        country=country_code,
    )


def _resolve_authorship_institutions(
    authorship: WorkAuthorship,
    *,
    profile_institutions: dict[str, list[InstitutionRef]],
) -> list[InstitutionRef]:
    # 1. Publication-specific affiliation extracted into first-class columns.
    refs = _institution_refs_from_fields(
        institutions=authorship.institutions,
        institution_ids=authorship.institution_ids,
        countries=authorship.countries,
    )
    if refs:
        return refs

    # 2. Raw provider authorship metadata, if richer data was stored there.
    raw = authorship.raw_metadata if isinstance(authorship.raw_metadata, dict) else {}
    refs = _institution_refs_from_fields(
        institutions=raw.get("institutions"),
        institution_ids=raw.get("institution_ids"),
        countries=raw.get("countries"),
    )
    if refs:
        return refs

    # 3. Canonical author current/latest institution fallback.
    if authorship.canonical_author_id is not None:
        return profile_institutions.get(str(authorship.canonical_author_id), [])
    return []


def _institution_refs_from_fields(
    *,
    institutions: Any,
    institution_ids: Any,
    countries: Any,
) -> list[InstitutionRef]:
    raw_institutions = institutions if isinstance(institutions, list) else []
    raw_ids = institution_ids if isinstance(institution_ids, list) else []
    raw_countries = countries if isinstance(countries, list) else []

    refs: dict[str, InstitutionRef] = {}
    max_len = max(len(raw_institutions), len(raw_ids), len(raw_countries), 0)
    for index in range(max_len):
        raw = raw_institutions[index] if index < len(raw_institutions) else None
        provider_id = raw_ids[index] if index < len(raw_ids) else None
        country = raw_countries[index] if index < len(raw_countries) else None

        if isinstance(raw, dict):
            payload = dict(raw)
            payload.setdefault("id", provider_id)
            payload.setdefault("country_code", country)
            ref = normalize_institution(payload)
        elif raw is not None:
            ref = normalize_institution(
                {
                    "id": provider_id,
                    "name": raw,
                    "country_code": country,
                }
            )
        elif provider_id is not None:
            ref = normalize_institution(
                {
                    "id": provider_id,
                    "country_code": country,
                }
            )
        else:
            ref = None

        if ref is not None:
            refs[ref.key] = _merge_institution_refs(refs.get(ref.key), ref)
    return list(refs.values())


def _merge_institution_refs(
    existing: InstitutionRef | None,
    candidate: InstitutionRef,
) -> InstitutionRef:
    if existing is None:
        return candidate
    return InstitutionRef(
        key=existing.key,
        id=existing.id,
        name=_best_display_label(existing.name, candidate.name),
        country=existing.country or candidate.country,
    )


def _best_display_label(existing: str | None, candidate: str) -> str:
    text = _clean_display_text(candidate)
    if not text:
        return existing or text
    if not existing:
        return text
    return text if _display_label_score(text) > _display_label_score(existing) else existing


def _display_label_score(value: str) -> tuple[int, int, int]:
    letters = [char for char in value if char.isalpha()]
    uppercase = sum(1 for char in letters if char.isupper())
    all_lower = int(value == value.lower())
    return (0 if all_lower else 1, uppercase, len(value))


def _clean_institution_id(value: Any) -> str | None:
    text = _clean_display_text(value)
    if not text:
        return None
    if "/" in text:
        text = text.rstrip("/").split("/")[-1]
    return text


def _clean_display_text(value: Any) -> str:
    return _WHITESPACE_RE.sub(" ", str(value or "").strip())


def _clean_country(value: Any) -> str | None:
    text = _clean_display_text(value)
    return text.upper() if text else None


def _normalize_institution_name(value: str | None) -> str | None:
    text = _clean_display_text(value).lower()
    if not text:
        return None
    text = _INSTITUTION_PUNCT_RE.sub(" ", text)
    text = _WHITESPACE_RE.sub(" ", text).strip()
    return text or None
