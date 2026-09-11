"""Selected-author work coverage synchronization.

`work_authorships.canonical_author_id` is the authoritative author-to-work
relationship. `author_works` is maintained as a derived provider-work index for
existing author identity overlap code.

Sync completeness statuses:
- complete: crawl finished AND provider-reported totals verify full retrieval
- partial: some works persisted but crawl/verification did not finish
- stale: previously complete coverage whose TTL has expired (effective status)
- failed: sync could not produce reliable coverage
"""

from __future__ import annotations

import asyncio
import logging
import time
import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.db.models import (
    AuthorWorkSyncState,
    CanonicalAuthor,
    ProviderAuthorRecord,
    ProviderWorkRecord,
    WorkAuthorship,
)
from app.integrations.arxiv.client import ArxivApiError, search_arxiv_publications_by_authors
from app.integrations.openalex.author_works import search_works_by_author_ids
from app.integrations.openalex.client import OpenAlexApiError
from app.services.work_persistence.candidate import candidate_from_provider_result
from app.services.work_persistence.repository import WorkPersistenceRepository
from app.services.work_persistence.service import WorkPersistenceService

logger = logging.getLogger(__name__)

SYNC_BATCH_SIZE = 40

STATUS_COMPLETE = "complete"
STATUS_PARTIAL = "partial"
STATUS_STALE = "stale"
STATUS_FAILED = "failed"
STATUS_NEVER = "never"

# Legacy statuses still readable from older rows.
_LEGACY_COMPLETE = {"success", "fresh", STATUS_COMPLETE}
_LEGACY_FAILED = {"provider_failed", STATUS_FAILED}
_LEGACY_PARTIAL = {"timeout", "skipped_timeout", STATUS_PARTIAL}

INCOMPLETE_STATUSES = {
    STATUS_PARTIAL,
    STATUS_FAILED,
    "skipped_timeout",
    "timeout",
    "provider_failed",
}

_sync_locks: dict[str, asyncio.Lock] = {}
_sync_locks_guard = asyncio.Lock()

SyncProgressCallback = Callable[[dict[str, Any]], Awaitable[None]]


@dataclass(frozen=True)
class SyncProviderRecord:
    id: uuid.UUID
    canonical_author_id: uuid.UUID
    provider: str
    provider_author_id: str
    display_name: str
    works_count: int | None


@dataclass(frozen=True)
class SyncProviderGroup:
    canonical_author_id: uuid.UUID
    provider: str
    records: tuple[SyncProviderRecord, ...]


@dataclass
class FetchResult:
    rows: list[dict[str, Any]] = field(default_factory=list)
    finished: bool = False
    error_message: str | None = None
    provider_reported_count: int | None = None
    unique_fetched: int = 0
    rate_limited: bool = False
    resume_cursor: str | None = None
    pages_fetched: int = 0
    new_works: int = 0


async def _lock_for_key(key: str) -> asyncio.Lock:
    async with _sync_locks_guard:
        lock = _sync_locks.get(key)
        if lock is None:
            lock = asyncio.Lock()
            _sync_locks[key] = lock
        return lock


def normalize_stored_status(status: str | None) -> str:
    text = str(status or STATUS_NEVER).strip().lower()
    if text in _LEGACY_COMPLETE:
        return STATUS_COMPLETE
    if text in _LEGACY_FAILED:
        return STATUS_FAILED
    if text in _LEGACY_PARTIAL:
        return STATUS_PARTIAL
    if text == STATUS_STALE:
        return STATUS_STALE
    return text or STATUS_NEVER


def is_rate_limit_error(exc: BaseException) -> bool:
    status = getattr(exc, "status_code", None)
    if status == 429:
        return True
    message = str(exc or "").lower()
    return "rate limit" in message or "too many requests" in message or "429" in message


def verify_crawl_completeness(
    *,
    crawl_finished: bool,
    fetch_failed: bool,
    linked_work_count: int,
    provider_reported_count: int | None,
    profile_works_count: int | None,
    allow_unverified_pagination: bool = False,
) -> tuple[bool, str | None, int | None]:
    """Return (ok, error_message, expected_total_used).

    Completeness requires a finished crawl with no fetch failure AND a
    provider-reported (or profile) total that the **linked stored** work count
    meets. Without an expected total we cannot prove completeness unless
    ``allow_unverified_pagination`` is set (used only for non-blocking
    enrichment providers such as name-based arXiv).
    """
    expected = provider_reported_count
    if expected is None:
        expected = profile_works_count

    if fetch_failed:
        return False, "Provider fetch failed before the full result set was retrieved.", expected
    if not crawl_finished:
        return False, "Provider crawl did not finish; coverage is partial.", expected
    if expected is None:
        if allow_unverified_pagination:
            return (
                False,
                "Provider did not report a verifiable total; treating coverage as unverified.",
                None,
            )
        return (
            False,
            "Provider did not report a total work count; completeness cannot be verified.",
            None,
        )
    if expected < 0:
        return False, "Provider reported an invalid total work count.", expected
    if linked_work_count < expected:
        return (
            False,
            (
                f"Linked {linked_work_count} stored publication(s) but provider "
                f"reported {expected}; coverage is incomplete."
            ),
            expected,
        )
    return True, None, expected


class AuthorWorkSyncService:
    """Repair and refresh stored publication coverage for selected authors."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.settings = get_settings()

    async def synchronize_selected_authors(
        self,
        authors: list[dict[str, Any]],
        *,
        timeout_seconds: float | None = None,
        on_progress: SyncProgressCallback | None = None,
    ) -> list[dict[str, Any]]:
        records = await self._load_selected_provider_records(authors)
        groups = self._group_provider_records(records)
        deadline = (
            time.monotonic() + max(float(timeout_seconds), 0.0)
            if timeout_seconds is not None
            else None
        )
        author_names = {
            str(group.canonical_author_id): (
                group.records[0].display_name if group.records else "Selected author"
            )
            for group in groups
        }
        author_order = list(dict.fromkeys(str(group.canonical_author_id) for group in groups))
        authors_total = max(len(author_order), 1)
        completed_authors: set[str] = set()

        async def _emit(**kwargs: Any) -> None:
            if on_progress is None:
                return
            author_id = kwargs.get("canonical_author_id")
            author_index = 0
            if author_id and author_id in author_order:
                author_index = author_order.index(str(author_id)) + 1
            elif completed_authors:
                author_index = len(completed_authors)
            payload = {
                "phase": kwargs.get("phase") or "syncing",
                "current_author": kwargs.get("current_author"),
                "canonical_author_id": author_id,
                "author_index": author_index,
                "authors_completed": len(completed_authors),
                "authors_total": len(author_order),
                "publications_processed": kwargs.get("publications_processed"),
                "publications_total": kwargs.get("publications_total"),
                "provider": kwargs.get("provider"),
                "sync_status": kwargs.get("sync_status"),
                "status": kwargs.get("status") or kwargs.get("sync_status"),
                "rate_limited": bool(kwargs.get("rate_limited")),
            }
            await on_progress(payload)

        await _emit(phase="checking", authors_total=authors_total)

        selected_author_ids = _selected_author_ids(authors)
        stats: list[dict[str, Any]] = []
        for group in groups:
            author_key = str(group.canonical_author_id)
            display_name = author_names.get(author_key) or "Selected author"
            expected_total = _profile_expected_total(group)

            if _deadline_exceeded(deadline):
                stored = await self._stored_provider_work_count(
                    group.canonical_author_id, group.provider
                )
                existing_state = await self._load_state(group)
                stat = await self._mark_group_incomplete(
                    group,
                    display_name=display_name,
                    status=STATUS_PARTIAL,
                    error_message="Sync timed out before this author/provider started.",
                    stored_work_count=stored,
                    provider_work_count=expected_total
                    or (existing_state.provider_work_count if existing_state else None),
                    rate_limited=False,
                    resume_cursor=existing_state.resume_cursor if existing_state else None,
                )
                stats.append(stat)
                completed_authors.add(author_key)
                await _emit(
                    phase="syncing",
                    current_author=display_name,
                    canonical_author_id=author_key,
                    provider=group.provider,
                    sync_status=STATUS_PARTIAL,
                    status=STATUS_PARTIAL,
                    publications_total=expected_total,
                )
                continue

            key = f"{group.canonical_author_id}|{group.provider}"
            # Process-local lock; also take a DB row lock when supported.
            lock = await _lock_for_key(key)

            async def _group_progress(
                *,
                publications_processed: int | None = None,
                publications_total: int | None = None,
                sync_status: str | None = None,
                phase: str = "syncing",
                rate_limited: bool = False,
            ) -> None:
                await _emit(
                    phase=phase,
                    current_author=display_name,
                    canonical_author_id=author_key,
                    provider=group.provider,
                    publications_processed=publications_processed,
                    publications_total=(
                        publications_total
                        if publications_total is not None
                        else expected_total
                    ),
                    sync_status=sync_status,
                    status=sync_status,
                    rate_limited=rate_limited,
                )

            async with lock:
                await _group_progress(
                    phase="syncing",
                    publications_processed=0,
                    sync_status=STATUS_STALE,
                )
                stats.append(
                    await self._sync_provider_group(
                        group,
                        deadline=deadline,
                        display_name=display_name,
                        on_progress=_group_progress,
                    )
                )

            completed_authors.add(author_key)
            final_stat = stats[-1]
            await _emit(
                phase="syncing",
                current_author=display_name,
                canonical_author_id=author_key,
                provider=group.provider,
                publications_processed=final_stat.get("stored_work_count_after"),
                publications_total=final_stat.get("provider_work_count")
                or expected_total
                or final_stat.get("fetched_work_count")
                or final_stat.get("stored_work_count_after"),
                sync_status=final_stat.get("status"),
                status=final_stat.get("status"),
                rate_limited=bool(final_stat.get("rate_limited")),
            )

        covered_authors = {str(row.get("canonical_author_id") or "") for row in stats}
        for author_id in selected_author_ids:
            if author_id in covered_authors:
                continue
            display = next(
                (
                    str(row.get("display_name") or "").strip()
                    for row in authors
                    if str(row.get("canonical_author_id") or "").strip() == author_id
                ),
                "Selected author",
            ) or "Selected author"
            stats.append(
                {
                    "canonical_author_id": author_id,
                    "provider": None,
                    "display_name": display,
                    "stored_work_count_before": 0,
                    "existing_links_repaired": 0,
                    "fetched_work_count": 0,
                    "new_works": 0,
                    "stored_work_count_after": 0,
                    "provider_work_count": None,
                    "status": STATUS_FAILED,
                    "network_skipped": True,
                    "error_message": (
                        "No OpenAlex/arXiv provider identity is linked for this author, "
                        "so a verified complete corpus cannot be built."
                    ),
                    "rate_limited": False,
                    "coverage_verified": False,
                    "last_synced_at": None,
                }
            )
        return stats

    def _group_provider_records(
        self,
        records: list[SyncProviderRecord],
    ) -> list[SyncProviderGroup]:
        grouped: dict[tuple[uuid.UUID, str], list[SyncProviderRecord]] = {}
        for record in records:
            grouped.setdefault(
                (record.canonical_author_id, record.provider),
                [],
            ).append(record)
        return [
            SyncProviderGroup(
                canonical_author_id=canonical_author_id,
                provider=provider,
                records=tuple(sorted(rows, key=lambda row: row.provider_author_id)),
            )
            for (canonical_author_id, provider), rows in sorted(
                grouped.items(), key=lambda item: (str(item[0][0]), item[0][1])
            )
        ]

    async def _load_selected_provider_records(
        self,
        authors: list[dict[str, Any]],
    ) -> list[SyncProviderRecord]:
        selected_ids: list[uuid.UUID] = []
        seen: set[str] = set()
        for row in authors:
            raw_id = str(row.get("canonical_author_id") or "").strip()
            try:
                author_id = uuid.UUID(raw_id)
            except (TypeError, ValueError):
                continue
            key = str(author_id)
            if key in seen:
                continue
            seen.add(key)
            selected_ids.append(author_id)
        if not selected_ids:
            return []

        result = await self.session.execute(
            select(ProviderAuthorRecord, CanonicalAuthor)
            .join(CanonicalAuthor, ProviderAuthorRecord.canonical_author_id == CanonicalAuthor.id)
            .where(ProviderAuthorRecord.canonical_author_id.in_(selected_ids))
        )
        records: list[SyncProviderRecord] = []
        seen_records: set[tuple[str, str, str]] = set()
        for provider_record, canonical_author in result.all():
            provider = str(provider_record.provider or "").strip().lower()
            if provider not in {"openalex", "arxiv"}:
                continue
            provider_author_id = _canonical_provider_author_id(
                provider, provider_record.provider_author_id
            )
            if not provider_author_id:
                continue
            key = (
                str(provider_record.canonical_author_id),
                provider,
                provider_author_id,
            )
            if key in seen_records:
                continue
            seen_records.add(key)
            records.append(
                SyncProviderRecord(
                    id=provider_record.id,
                    canonical_author_id=provider_record.canonical_author_id,
                    provider=provider,
                    provider_author_id=provider_author_id,
                    display_name=provider_record.display_name
                    or canonical_author.preferred_name,
                    works_count=provider_record.works_count,
                )
            )
        return records

    def effective_status(self, state: AuthorWorkSyncState | None) -> str:
        if state is None:
            return STATUS_NEVER
        stored = normalize_stored_status(state.status)
        if stored != STATUS_COMPLETE:
            return stored
        if not self._verified_complete_coverage(state):
            return STATUS_STALE
        if self._complete_within_ttl(state):
            return STATUS_COMPLETE
        return STATUS_STALE

    def _verified_complete_coverage(self, state: AuthorWorkSyncState) -> bool:
        """Refuse to treat coverage as complete without a verified provider total."""
        if normalize_stored_status(state.status) != STATUS_COMPLETE:
            return False
        if state.provider_work_count is None:
            return False
        if int(state.stored_work_count or 0) < int(state.provider_work_count):
            return False
        if state.resume_cursor:
            return False
        return True

    def _complete_within_ttl(self, state: AuthorWorkSyncState) -> bool:
        synced_at = state.last_successful_synced_at or state.last_synced_at
        if synced_at is None:
            return False
        if synced_at.tzinfo is None:
            synced_at = synced_at.replace(tzinfo=timezone.utc)
        age = (datetime.now(timezone.utc) - synced_at).total_seconds()
        return age < self.settings.author_work_sync_ttl_seconds

    async def _sync_provider_group(
        self,
        group: SyncProviderGroup,
        *,
        deadline: float | None = None,
        display_name: str,
        on_progress: Callable[..., Awaitable[None]] | None = None,
    ) -> dict[str, Any]:
        started = time.perf_counter()
        before_count = await self._stored_provider_work_count(
            group.canonical_author_id, group.provider
        )
        repaired = 0
        for record in group.records:
            repaired += await self._repair_existing_links(record)
        after_repair_count = await self._stored_provider_work_count(
            group.canonical_author_id, group.provider
        )
        await self.session.commit()

        state = await self._load_state(group)
        effective = self.effective_status(state)
        profile_expected = _profile_expected_total(group)
        expected_total = (
            state.provider_work_count
            if state and state.provider_work_count is not None
            else profile_expected
        )

        if effective == STATUS_COMPLETE:
            # Fresh verified complete coverage: reuse stored works, no provider HTTP.
            stat = {
                "canonical_author_id": str(group.canonical_author_id),
                "provider": group.provider,
                "display_name": display_name,
                "stored_work_count_before": before_count,
                "existing_links_repaired": repaired,
                "fetched_work_count": 0,
                "new_works": 0,
                "stored_work_count_after": after_repair_count,
                "provider_work_count": (
                    state.provider_work_count if state else expected_total
                ),
                "status": STATUS_COMPLETE,
                "network_skipped": True,
                "error_message": None,
                "rate_limited": False,
                "coverage_verified": True,
                "last_synced_at": (
                    (state.last_successful_synced_at or state.last_synced_at).isoformat()
                    if state and (state.last_successful_synced_at or state.last_synced_at)
                    else None
                ),
            }
            self._log_stats(stat, started)
            return stat

        if on_progress is not None:
            await on_progress(
                publications_processed=after_repair_count,
                publications_total=expected_total,
                sync_status=effective if effective != STATUS_NEVER else STATUS_STALE,
                phase="syncing",
            )

        # Mark attempt / expose stale before network work. Preserve prior success stamp.
        prior_success_at = (
            state.last_successful_synced_at if state else None
        )
        prior_complete = bool(
            state
            and normalize_stored_status(state.status) == STATUS_COMPLETE
            and self._verified_complete_coverage(state)
        )
        await self._upsert_state(
            group,
            stored_work_count=after_repair_count,
            provider_work_count=expected_total,
            status=STATUS_STALE if effective == STATUS_STALE else STATUS_PARTIAL,
            error_message=None,
            mark_attempt=True,
            mark_success=False,
            resume_cursor=state.resume_cursor if state else None,
            preserve_last_success=True,
        )
        await self.session.commit()

        fetch_result = FetchResult(finished=False)
        try:
            fetch_result = await self._crawl_and_persist_group(
                group,
                deadline=deadline,
                on_progress=on_progress,
                publications_total=expected_total or profile_expected,
                resume_cursor=state.resume_cursor if state else None,
            )
        except Exception as exc:
            fetch_result = FetchResult(
                finished=False,
                error_message=str(exc) or "Provider request failed.",
                rate_limited=is_rate_limit_error(exc),
            )
            logger.warning(
                "author_work_sync provider_failed author=%s provider=%s error=%s",
                group.canonical_author_id,
                group.provider,
                exc,
            )

        after_count = await self._stored_provider_work_count(
            group.canonical_author_id, group.provider
        )
        # Integrity is based on linked stored authorships, not crawl ID sets.
        # Crawl unique IDs can exceed linked rows when persist/authorship fails.
        ok, integrity_error, expected_used = verify_crawl_completeness(
            crawl_finished=fetch_result.finished,
            fetch_failed=bool(fetch_result.error_message) and not fetch_result.finished,
            linked_work_count=after_count,
            provider_reported_count=fetch_result.provider_reported_count,
            profile_works_count=profile_expected if group.provider == "openalex" else None,
            allow_unverified_pagination=group.provider == "arxiv",
        )
        # Finished crawl with no error but integrity failed → partial, not failed.
        if fetch_result.finished and not fetch_result.rate_limited and fetch_result.error_message is None:
            fetch_failed_flag = False
        else:
            fetch_failed_flag = bool(fetch_result.error_message) and after_count == before_count

        rate_limited = bool(fetch_result.rate_limited)
        error_message = fetch_result.error_message or integrity_error

        # OpenAlex (and any provider with a verifiable total) may be complete.
        # arXiv name-search without a verifiable total stays partial/unverified.
        if ok and not rate_limited:
            status = STATUS_COMPLETE
            error_message = None
            resume_cursor = None
            mark_success = True
        elif after_count > 0 or fetch_result.pages_fetched > 0 or prior_complete:
            status = STATUS_PARTIAL
            mark_success = False
            resume_cursor = fetch_result.resume_cursor
            if rate_limited and not error_message:
                error_message = (
                    f"{group.provider} rate limit reached. Existing stored data was preserved."
                )
            elif not error_message:
                error_message = integrity_error or "Provider crawl did not finish; coverage is partial."
        else:
            status = STATUS_FAILED
            mark_success = False
            resume_cursor = fetch_result.resume_cursor
            if not error_message:
                error_message = "Provider crawl did not finish and no works were stored."
            if fetch_failed_flag and not rate_limited:
                status = STATUS_FAILED

        # Never demote trustworthy prior complete data by wiping success timestamps.
        # Status may become partial/failed, but last_successful_synced_at stays.
        provider_count_to_store = expected_used
        if provider_count_to_store is None:
            provider_count_to_store = fetch_result.provider_reported_count or (
                profile_expected if group.provider == "openalex" else None
            )
        # Do not self-certify completeness from len(fetched).

        await self._upsert_state(
            group,
            stored_work_count=after_count,
            provider_work_count=provider_count_to_store,
            status=status,
            error_message=error_message,
            mark_attempt=True,
            mark_success=mark_success,
            resume_cursor=resume_cursor,
            preserve_last_success=not mark_success,
        )
        await self.session.commit()

        new_works = int(fetch_result.new_works or 0)

        stat = {
            "canonical_author_id": str(group.canonical_author_id),
            "provider": group.provider,
            "display_name": display_name,
            "stored_work_count_before": before_count,
            "existing_links_repaired": repaired,
            "fetched_work_count": fetch_result.unique_fetched or max(after_count - before_count, 0),
            "new_works": new_works,
            "stored_work_count_after": after_count,
            "provider_work_count": provider_count_to_store,
            "status": status,
            "network_skipped": False,
            "error_message": error_message,
            "rate_limited": rate_limited,
            "coverage_verified": status == STATUS_COMPLETE,
            "resume_cursor": resume_cursor,
            "pages_fetched": fetch_result.pages_fetched,
            "last_synced_at": datetime.now(timezone.utc).isoformat(),
            "prior_successful_synced_at": (
                prior_success_at.isoformat() if prior_success_at else None
            ),
        }
        if after_count == 0:
            logger.warning(
                "author_work_sync_no_coverage author=%s provider=%s status=%s "
                "rate_limited=%s error=%s",
                group.canonical_author_id,
                group.provider,
                status,
                rate_limited,
                error_message,
            )
        elif status != STATUS_COMPLETE:
            logger.warning(
                "author_work_sync_incomplete author=%s provider=%s status=%s "
                "stored=%s expected=%s pages=%s rate_limited=%s resume=%s error=%s",
                group.canonical_author_id,
                group.provider,
                status,
                after_count,
                provider_count_to_store,
                fetch_result.pages_fetched,
                rate_limited,
                resume_cursor,
                error_message,
            )
        self._log_stats(stat, started)
        return stat

    async def _crawl_and_persist_group(
        self,
        group: SyncProviderGroup,
        *,
        deadline: float | None,
        on_progress: Callable[..., Awaitable[None]] | None,
        publications_total: int | None,
        resume_cursor: str | None,
    ) -> FetchResult:
        if group.provider == "openalex":
            if not self.settings.openalex_configured:
                raise OpenAlexApiError("OpenAlex is not configured.", status_code=503)
            return await self._crawl_openalex_group(
                group,
                deadline=deadline,
                on_progress=on_progress,
                publications_total=publications_total,
                resume_cursor=resume_cursor,
            )
        if group.provider == "arxiv":
            if not self.settings.arxiv_configured:
                raise ArxivApiError("arXiv is not configured.", status_code=503)
            return await self._crawl_arxiv_group(
                group,
                deadline=deadline,
                on_progress=on_progress,
                publications_total=publications_total,
                resume_cursor=resume_cursor,
            )
        return FetchResult(
            finished=False,
            error_message=f"Unsupported provider for sync: {group.provider}",
        )

    async def _crawl_openalex_group(
        self,
        group: SyncProviderGroup,
        *,
        deadline: float | None,
        on_progress: Callable[..., Awaitable[None]] | None,
        publications_total: int | None,
        resume_cursor: str | None,
    ) -> FetchResult:
        author_ids = [record.provider_author_id for record in group.records]
        cursor: str | None = resume_cursor or "*"
        seen_work_ids: set[str] = set()
        # Seed seen set from already-stored provider works so resume integrity is honest.
        existing_ids = await self._stored_provider_work_ids(
            group.canonical_author_id, group.provider
        )
        seen_work_ids.update(existing_ids)

        provider_reported_count: int | None = None
        pages_fetched = 0
        new_works = 0
        finished = True
        error_message: str | None = None
        rate_limited = False
        next_resume: str | None = None

        while cursor is not None:
            if _deadline_exceeded(deadline):
                finished = False
                error_message = "Sync timed out while fetching OpenAlex publications."
                next_resume = cursor
                logger.warning(
                    "author_work_sync_timeout author=%s provider=openalex page=%s cursor=%s",
                    group.canonical_author_id,
                    pages_fetched + 1,
                    cursor,
                )
                break
            try:
                page = await search_works_by_author_ids(
                    author_id_groups=[author_ids],
                    limit=SYNC_BATCH_SIZE,
                    cursor=cursor,
                )
            except Exception as exc:
                finished = False
                rate_limited = is_rate_limit_error(exc)
                error_message = str(exc) or "OpenAlex request failed."
                next_resume = cursor
                logger.warning(
                    "author_work_sync_page_failed author=%s provider=openalex "
                    "page=%s cursor=%s rate_limited=%s error=%s",
                    group.canonical_author_id,
                    pages_fetched + 1,
                    cursor,
                    rate_limited,
                    exc,
                )
                break

            pages_fetched += 1
            page_count = page.get("count")
            if isinstance(page_count, int) and page_count >= 0:
                provider_reported_count = page_count

            page_rows: list[dict[str, Any]] = []
            for row in list(page.get("results") or []):
                if not isinstance(row, dict):
                    continue
                work_id = str(
                    row.get("openalex_id") or row.get("source_id") or row.get("id") or ""
                )
                if work_id and work_id in seen_work_ids:
                    continue
                if work_id:
                    seen_work_ids.add(work_id)
                page_rows.append(row)

            if page_rows:
                new_works += await self._persist_fetched_works_for_group(group, page_rows)

            stored_now = await self._stored_provider_work_count(
                group.canonical_author_id, group.provider
            )
            expected_now = provider_reported_count or publications_total
            await self._upsert_state(
                group,
                stored_work_count=stored_now,
                provider_work_count=expected_now,
                status=STATUS_PARTIAL,
                error_message=None,
                mark_attempt=True,
                mark_success=False,
                resume_cursor=(
                    str(page.get("next_cursor"))
                    if page.get("has_more") and page.get("next_cursor")
                    else None
                ),
                preserve_last_success=True,
            )
            await self.session.commit()

            if on_progress is not None:
                await on_progress(
                    publications_processed=len(seen_work_ids),
                    publications_total=expected_now,
                    sync_status=STATUS_PARTIAL,
                    phase="syncing",
                )

            if page.get("has_more") and page.get("next_cursor"):
                cursor = str(page.get("next_cursor"))
                next_resume = cursor
            else:
                # Guard: empty page with leftover cursor must not silently complete.
                if page.get("next_cursor") and not list(page.get("results") or []):
                    finished = False
                    error_message = (
                        "OpenAlex returned an empty page with a continuation cursor; "
                        "refusing to mark coverage complete."
                    )
                    next_resume = str(page.get("next_cursor"))
                    logger.warning(
                        "author_work_sync_empty_page author=%s provider=openalex cursor=%s",
                        group.canonical_author_id,
                        next_resume,
                    )
                    break
                cursor = None
                next_resume = None

        unique_fetched = len(seen_work_ids)
        return FetchResult(
            rows=[],
            finished=finished and not rate_limited and error_message is None,
            error_message=error_message,
            provider_reported_count=provider_reported_count,
            unique_fetched=unique_fetched,
            rate_limited=rate_limited,
            resume_cursor=next_resume if not (finished and error_message is None) else None,
            pages_fetched=pages_fetched,
            new_works=new_works,
        )

    async def _crawl_arxiv_group(
        self,
        group: SyncProviderGroup,
        *,
        deadline: float | None,
        on_progress: Callable[..., Awaitable[None]] | None,
        publications_total: int | None,
        resume_cursor: str | None,
    ) -> FetchResult:
        # arXiv identity is display-name based; use the first record's name.
        display_name = group.records[0].display_name if group.records else ""
        cursor: str | None = resume_cursor
        seen_work_ids: set[str] = set(
            await self._stored_provider_work_ids(group.canonical_author_id, group.provider)
        )
        pages_fetched = 0
        new_works = 0
        finished = True
        error_message: str | None = None
        rate_limited = False
        next_resume: str | None = None

        while True:
            if _deadline_exceeded(deadline):
                finished = False
                error_message = "Sync timed out while fetching arXiv publications."
                next_resume = cursor
                break
            try:
                page = await search_arxiv_publications_by_authors(
                    author_names=[display_name],
                    limit=SYNC_BATCH_SIZE,
                    cursor=cursor,
                )
            except Exception as exc:
                finished = False
                rate_limited = is_rate_limit_error(exc)
                error_message = str(exc) or "arXiv request failed."
                next_resume = cursor
                logger.warning(
                    "author_work_sync_page_failed author=%s provider=arxiv "
                    "page=%s cursor=%s rate_limited=%s error=%s",
                    group.canonical_author_id,
                    pages_fetched + 1,
                    cursor,
                    rate_limited,
                    exc,
                )
                break

            pages_fetched += 1
            # Do NOT use Atom totalResults as an integrity target: results are
            # post-filtered by author-name matching, so totals over-count.

            page_rows: list[dict[str, Any]] = []
            for row in list(page.get("results") or []):
                if not isinstance(row, dict):
                    continue
                work_id = str(
                    row.get("source_id") or row.get("arxiv_id") or row.get("id") or ""
                )
                if work_id and work_id in seen_work_ids:
                    continue
                if work_id:
                    seen_work_ids.add(work_id)
                page_rows.append(row)

            if page_rows:
                new_works += await self._persist_fetched_works_for_group(group, page_rows)

            stored_now = await self._stored_provider_work_count(
                group.canonical_author_id, group.provider
            )
            expected_now = publications_total
            await self._upsert_state(
                group,
                stored_work_count=stored_now,
                provider_work_count=expected_now,
                status=STATUS_PARTIAL,
                error_message=None,
                mark_attempt=True,
                mark_success=False,
                resume_cursor=(
                    str(page.get("next_cursor"))
                    if page.get("has_more") and page.get("next_cursor")
                    else None
                ),
                preserve_last_success=True,
            )
            await self.session.commit()

            if on_progress is not None:
                await on_progress(
                    publications_processed=len(seen_work_ids),
                    publications_total=expected_now,
                    sync_status=STATUS_PARTIAL,
                    phase="syncing",
                )

            if page.get("has_more") and page.get("next_cursor"):
                cursor = str(page.get("next_cursor"))
                next_resume = cursor
            else:
                break

        return FetchResult(
            rows=[],
            finished=finished and not rate_limited and error_message is None,
            error_message=error_message,
            provider_reported_count=None,
            unique_fetched=len(seen_work_ids),
            rate_limited=rate_limited,
            resume_cursor=next_resume if not (finished and error_message is None) else None,
            pages_fetched=pages_fetched,
            new_works=new_works,
        )

    async def _mark_group_incomplete(
        self,
        group: SyncProviderGroup,
        *,
        display_name: str,
        status: str,
        error_message: str,
        stored_work_count: int,
        provider_work_count: int | None = None,
        rate_limited: bool = False,
        resume_cursor: str | None = None,
    ) -> dict[str, Any]:
        await self._upsert_state(
            group,
            stored_work_count=stored_work_count,
            provider_work_count=provider_work_count,
            status=status,
            error_message=error_message,
            mark_attempt=True,
            mark_success=False,
            resume_cursor=resume_cursor,
            preserve_last_success=True,
        )
        await self.session.commit()
        return {
            "canonical_author_id": str(group.canonical_author_id),
            "provider": group.provider,
            "display_name": display_name,
            "stored_work_count_before": stored_work_count,
            "existing_links_repaired": 0,
            "fetched_work_count": 0,
            "new_works": 0,
            "stored_work_count_after": stored_work_count,
            "provider_work_count": provider_work_count,
            "status": status,
            "network_skipped": True,
            "error_message": error_message,
            "rate_limited": rate_limited,
            "coverage_verified": False,
            "resume_cursor": resume_cursor,
            "last_synced_at": None,
        }

    async def _repair_existing_links(self, record: SyncProviderRecord) -> int:
        provider_author_ids = {record.provider_author_id}
        if record.provider == "openalex":
            provider_author_ids.add(f"https://openalex.org/{record.provider_author_id}")

        result = await self.session.execute(
            select(WorkAuthorship, ProviderWorkRecord)
            .join(
                ProviderWorkRecord,
                (ProviderWorkRecord.canonical_work_id == WorkAuthorship.canonical_work_id)
                & (ProviderWorkRecord.provider == WorkAuthorship.provider),
            )
            .where(
                WorkAuthorship.provider == record.provider,
                WorkAuthorship.provider_author_id.in_(provider_author_ids),
            )
        )
        repo = WorkPersistenceRepository(self.session)
        repaired = 0
        for authorship, provider_work in result.all():
            if authorship.canonical_author_id is None:
                authorship.canonical_author_id = record.canonical_author_id
                repaired += 1
            if authorship.canonical_author_id == record.canonical_author_id:
                await repo.ensure_author_work(
                    provider_record_id=record.id,
                    provider_work_id=provider_work.provider_work_id,
                    provider=record.provider,
                    title=_raw_title(provider_work.raw_metadata),
                    publication_year=_raw_publication_year(provider_work.raw_metadata),
                )
        if repaired:
            await self.session.flush()
        return repaired

    async def _persist_fetched_works_for_group(
        self,
        group: SyncProviderGroup,
        rows: list[dict[str, Any]],
    ) -> int:
        new_works = 0
        for start in range(0, len(rows), SYNC_BATCH_SIZE):
            batch = rows[start : start + SYNC_BATCH_SIZE]
            persistence = WorkPersistenceService(self.session)
            for row in batch:
                record = _matching_group_record(group, row)
                candidate = candidate_from_provider_result(row, provider=group.provider)
                if candidate is None:
                    continue
                _ensure_selected_provider_author(candidate.raw_metadata, record)
                canonical, created = await persistence.resolve_candidate(candidate)
                if created:
                    new_works += 1
                # Always refresh authorships so coauthors with known provider
                # records get canonical links (needed for multi-author intersection).
                await WorkPersistenceRepository(self.session).replace_work_authorships(
                    canonical_work_id=canonical.id,
                    provider=record.provider,
                    provider_work_id=candidate.provider_work_id,
                    raw_metadata=candidate.raw_metadata,
                )
                # Guarantee the selected author is linked even if provider metadata
                # omitted them from the authorship list.
                if not await self._has_author_authorship_link(
                    canonical_work_id=canonical.id,
                    record=record,
                ):
                    await self._ensure_selected_authorship_link(
                        canonical_work_id=canonical.id,
                        record=record,
                        provider_work_id=candidate.provider_work_id,
                    )
                await WorkPersistenceRepository(self.session).ensure_author_work(
                    provider_record_id=record.id,
                    provider_work_id=candidate.provider_work_id,
                    provider=record.provider,
                    title=candidate.title,
                    publication_year=candidate.publication_year,
                )
            await self.session.commit()
        return new_works

    async def _ensure_selected_authorship_link(
        self,
        *,
        canonical_work_id: uuid.UUID,
        record: SyncProviderRecord,
        provider_work_id: str,
    ) -> None:
        existing_positions = (
            await self.session.execute(
                select(WorkAuthorship.author_position).where(
                    WorkAuthorship.canonical_work_id == canonical_work_id,
                    WorkAuthorship.provider == record.provider,
                )
            )
        ).all()
        used = {int(row[0]) for row in existing_positions if row[0] is not None}
        position = 0
        while position in used:
            position += 1
        self.session.add(
            WorkAuthorship(
                id=uuid.uuid4(),
                canonical_work_id=canonical_work_id,
                provider=record.provider,
                provider_author_id=record.provider_author_id,
                canonical_author_id=record.canonical_author_id,
                display_name=record.display_name,
                author_position=position,
                institutions=[],
                institution_ids=[],
                countries=[],
            )
        )
        await self.session.flush()
        logger.info(
            "author_work_sync_injected_selected_authorship author=%s provider=%s "
            "provider_author_id=%s work=%s position=%s",
            record.canonical_author_id,
            record.provider,
            record.provider_author_id,
            provider_work_id,
            position,
        )

    async def _has_author_authorship_link(
        self,
        *,
        canonical_work_id: uuid.UUID,
        record: SyncProviderRecord,
    ) -> bool:
        provider_author_ids = {record.provider_author_id}
        if record.provider == "openalex":
            provider_author_ids.add(f"https://openalex.org/{record.provider_author_id}")
        existing = (
            await self.session.execute(
                select(WorkAuthorship.id).where(
                    WorkAuthorship.canonical_work_id == canonical_work_id,
                    WorkAuthorship.provider == record.provider,
                    WorkAuthorship.provider_author_id.in_(provider_author_ids),
                    WorkAuthorship.canonical_author_id == record.canonical_author_id,
                )
            )
        ).first()
        return existing is not None

    async def _load_state(
        self,
        group: SyncProviderGroup,
    ) -> AuthorWorkSyncState | None:
        return (
            await self.session.execute(
                select(AuthorWorkSyncState).where(
                    AuthorWorkSyncState.canonical_author_id == group.canonical_author_id,
                    AuthorWorkSyncState.provider == group.provider,
                )
            )
        ).scalar_one_or_none()

    async def _upsert_state(
        self,
        group: SyncProviderGroup,
        *,
        stored_work_count: int,
        provider_work_count: int | None,
        status: str,
        error_message: str | None,
        mark_attempt: bool,
        mark_success: bool,
        resume_cursor: str | None = None,
        preserve_last_success: bool = False,
    ) -> None:
        state = await self._load_state(group)
        now = datetime.now(timezone.utc)
        if state is None:
            state = AuthorWorkSyncState(
                id=uuid.uuid4(),
                canonical_author_id=group.canonical_author_id,
                provider=group.provider,
                last_synced_at=now if mark_success else None,
                last_successful_synced_at=now if mark_success else None,
                last_attempted_at=now if mark_attempt else None,
                stored_work_count=stored_work_count,
                provider_work_count=provider_work_count,
                status=status,
                error_message=error_message,
                resume_cursor=resume_cursor,
            )
            self.session.add(state)
        else:
            if mark_attempt:
                state.last_attempted_at = now
            if mark_success:
                state.last_synced_at = now
                state.last_successful_synced_at = now
                state.resume_cursor = None
            elif preserve_last_success or status in {
                STATUS_PARTIAL,
                STATUS_FAILED,
                STATUS_STALE,
            }:
                # Keep last_successful_synced_at; do not pretend this attempt succeeded.
                state.resume_cursor = resume_cursor
            state.stored_work_count = stored_work_count
            # Never clear a known provider total with None during a failed attempt.
            if provider_work_count is not None:
                state.provider_work_count = provider_work_count
            state.status = status
            state.error_message = error_message
            if mark_success:
                state.resume_cursor = None
            elif resume_cursor is not None or status != STATUS_COMPLETE:
                state.resume_cursor = resume_cursor
        await self.session.flush()

    async def _stored_provider_work_count(
        self,
        canonical_author_id: uuid.UUID,
        provider: str,
    ) -> int:
        return int(
            (
                await self.session.execute(
                    select(func.count(func.distinct(WorkAuthorship.canonical_work_id))).where(
                        WorkAuthorship.canonical_author_id == canonical_author_id,
                        WorkAuthorship.provider == provider,
                    )
                )
            ).scalar_one()
            or 0
        )

    async def _stored_provider_work_ids(
        self,
        canonical_author_id: uuid.UUID,
        provider: str,
    ) -> set[str]:
        rows = (
            await self.session.execute(
                select(ProviderWorkRecord.provider_work_id)
                .join(
                    WorkAuthorship,
                    WorkAuthorship.canonical_work_id == ProviderWorkRecord.canonical_work_id,
                )
                .where(
                    WorkAuthorship.canonical_author_id == canonical_author_id,
                    WorkAuthorship.provider == provider,
                    ProviderWorkRecord.provider == provider,
                )
            )
        ).all()
        return {str(row[0]) for row in rows if row[0]}

    def _log_stats(self, stat: dict[str, Any], started: float) -> None:
        logger.info(
            "author_work_sync_stats=%s elapsed_ms=%.2f",
            stat,
            (time.perf_counter() - started) * 1000,
        )


def _deadline_exceeded(deadline: float | None) -> bool:
    return deadline is not None and time.monotonic() >= deadline


def _selected_author_ids(authors: list[dict[str, Any]]) -> list[str]:
    selected: list[str] = []
    seen: set[str] = set()
    for row in authors:
        raw_id = str(row.get("canonical_author_id") or "").strip()
        if not raw_id or raw_id in seen:
            continue
        try:
            uuid.UUID(raw_id)
        except (TypeError, ValueError):
            continue
        seen.add(raw_id)
        selected.append(raw_id)
    return selected


def _profile_expected_total(group: SyncProviderGroup) -> int | None:
    totals = [record.works_count for record in group.records if record.works_count]
    if not totals:
        return None
    # Multiple OpenAlex IDs are OR'd into one crawl; profile counts may overlap,
    # so use the max as a lower-bound hint when meta.count is absent.
    return max(int(value) for value in totals)


def _matching_group_record(
    group: SyncProviderGroup,
    row: dict[str, Any],
) -> SyncProviderRecord:
    if len(group.records) == 1:
        return group.records[0]
    author_ids: set[str] = set()
    for author in list(row.get("authors") or []):
        if not isinstance(author, dict):
            continue
        short = _canonical_provider_author_id(
            group.provider,
            author.get("id") or author.get("openalex_id") or author.get("source_id"),
        )
        if short:
            author_ids.add(short)
        provider_ids = author.get("provider_ids")
        if isinstance(provider_ids, dict):
            for raw in list(provider_ids.get(group.provider) or []):
                short = _canonical_provider_author_id(group.provider, raw)
                if short:
                    author_ids.add(short)
    for record in group.records:
        if record.provider_author_id in author_ids:
            return record
    return group.records[0]


def _canonical_provider_author_id(provider: str, provider_author_id: Any) -> str | None:
    text = str(provider_author_id or "").strip()
    if not text:
        return None
    if provider == "openalex":
        text = text.rstrip("/").split("/")[-1]
    return text or None


def _raw_title(raw_metadata: dict[str, Any] | None) -> str | None:
    if not isinstance(raw_metadata, dict):
        return None
    title = raw_metadata.get("title")
    return " ".join(str(title).split()) if title else None


def _raw_publication_year(raw_metadata: dict[str, Any] | None) -> int | None:
    if not isinstance(raw_metadata, dict):
        return None
    try:
        return int(raw_metadata.get("publication_year"))
    except (TypeError, ValueError):
        return None


def _ensure_selected_provider_author(
    raw_metadata: dict[str, Any],
    record: SyncProviderRecord,
) -> None:
    if record.provider != "openalex":
        return
    authors = raw_metadata.get("authors")
    if not isinstance(authors, list):
        authors = []
        raw_metadata["authors"] = authors
    target = record.provider_author_id
    for author in authors:
        if not isinstance(author, dict):
            continue
        provider_author_id = _canonical_provider_author_id(
            record.provider,
            author.get("id") or author.get("openalex_id"),
        )
        if provider_author_id == target:
            author["id"] = target
            provider_ids = author.get("provider_ids")
            if not isinstance(provider_ids, dict):
                provider_ids = {}
            openalex_ids = list(provider_ids.get("openalex") or [])
            if target not in openalex_ids:
                openalex_ids.append(target)
            provider_ids["openalex"] = openalex_ids
            author["provider_ids"] = provider_ids
            return
    # Provider payload omitted the selected author — inject so authorship replace
    # and multi-author linking still attribute the work to them.
    next_position = 0
    for author in authors:
        if not isinstance(author, dict):
            continue
        try:
            next_position = max(next_position, int(author.get("author_position") or 0) + 1)
        except (TypeError, ValueError):
            next_position = max(next_position, 1)
    authors.append(
        {
            "id": target,
            "name": record.display_name,
            "display_name": record.display_name,
            "author_position": next_position,
            "provider_ids": {"openalex": [target], "orcid": [], "arxiv": []},
            "institutions": [],
            "institution_ids": [],
            "countries": [],
        }
    )
