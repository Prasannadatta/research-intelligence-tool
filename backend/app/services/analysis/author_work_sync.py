"""Selected-author work coverage synchronization.

`work_authorships.canonical_author_id` is the authoritative author-to-work
relationship. `author_works` is maintained as a derived provider-work index for
existing author identity overlap code.

Sync completeness statuses:
- complete: provider crawl finished; all available pages processed
- partial: some works persisted but crawl did not finish
- stale: previously complete coverage whose TTL has expired (effective status)
- failed: sync could not produce reliable coverage
"""

from __future__ import annotations

import asyncio
import logging
import time
import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
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

INCOMPLETE_STATUSES = {STATUS_PARTIAL, STATUS_FAILED, "skipped_timeout", "timeout", "provider_failed"}

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


@dataclass(frozen=True)
class FetchResult:
    rows: list[dict[str, Any]]
    finished: bool
    error_message: str | None = None


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
            }
            await on_progress(payload)

        await _emit(phase="checking", authors_total=authors_total)

        stats: list[dict[str, Any]] = []
        for group in groups:
            author_key = str(group.canonical_author_id)
            display_name = author_names.get(author_key) or "Selected author"
            expected_total = next(
                (record.works_count for record in group.records if record.works_count),
                None,
            )

            if _deadline_exceeded(deadline):
                stat = await self._mark_group_incomplete(
                    group,
                    display_name=display_name,
                    status=STATUS_PARTIAL,
                    error_message="Sync timed out before this author/provider started.",
                    stored_work_count=await self._stored_work_count(group.canonical_author_id),
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
            lock = await _lock_for_key(key)

            async def _group_progress(
                *,
                publications_processed: int | None = None,
                publications_total: int | None = None,
                sync_status: str | None = None,
                phase: str = "syncing",
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
                publications_total=expected_total
                or final_stat.get("fetched_work_count")
                or final_stat.get("stored_work_count_after"),
                sync_status=final_stat.get("status"),
                status=final_stat.get("status"),
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
        if self._complete_within_ttl(state):
            return STATUS_COMPLETE
        return STATUS_STALE

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
        before_count = await self._stored_work_count(group.canonical_author_id)
        repaired = 0
        for record in group.records:
            repaired += await self._repair_existing_links(record)
        after_repair_count = await self._stored_work_count(group.canonical_author_id)
        await self.session.commit()

        state = await self._load_state(group)
        effective = self.effective_status(state)
        expected_total = next(
            (record.works_count for record in group.records if record.works_count),
            state.provider_work_count if state else None,
        )

        if effective == STATUS_COMPLETE:
            # Fresh complete coverage: reuse stored works, no provider HTTP.
            stat = {
                "canonical_author_id": str(group.canonical_author_id),
                "provider": group.provider,
                "display_name": display_name,
                "stored_work_count_before": before_count,
                "existing_links_repaired": repaired,
                "fetched_work_count": 0,
                "new_works": 0,
                "stored_work_count_after": after_repair_count,
                "status": STATUS_COMPLETE,
                "network_skipped": True,
                "error_message": None,
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

        # Mark attempt / expose stale before network work.
        if effective == STATUS_STALE and state is not None:
            await self._upsert_state(
                group,
                stored_work_count=after_repair_count,
                provider_work_count=expected_total,
                status=STATUS_STALE,
                error_message=None,
                mark_attempt=True,
                mark_success=False,
            )
            await self.session.commit()

        fetched: list[dict[str, Any]] = []
        crawl_finished = True
        error_message: str | None = None
        new_works = 0
        fetch_failed = False

        for record in group.records:
            if _deadline_exceeded(deadline):
                crawl_finished = False
                error_message = "Sync timed out while fetching provider publications."
                break
            try:
                result = await self._fetch_provider_works(
                    record,
                    deadline=deadline,
                    on_page=on_progress,
                    publications_total=expected_total,
                    base_processed=len(fetched),
                )
            except Exception as exc:
                fetch_failed = True
                crawl_finished = False
                error_message = str(exc) or "Provider request failed."
                logger.warning(
                    "author_work_sync provider_failed author=%s provider=%s "
                    "provider_author_id=%s error=%s",
                    record.canonical_author_id,
                    record.provider,
                    record.provider_author_id,
                    exc,
                )
                continue

            if not result.finished:
                crawl_finished = False
                error_message = result.error_message or error_message
            if result.error_message and not error_message:
                error_message = result.error_message
            fetched.extend(result.rows)
            if result.rows:
                new_works += await self._persist_fetched_works(
                    record,
                    result.rows,
                    on_progress=on_progress,
                    publications_total=expected_total,
                    base_processed=max(0, len(fetched) - len(result.rows)),
                )
                repaired += await self._repair_existing_links(record)

        after_count = await self._stored_work_count(group.canonical_author_id)
        if fetch_failed and not fetched and after_count == before_count:
            status = STATUS_FAILED
            if not error_message:
                error_message = "Provider sync failed."
        elif crawl_finished and not fetch_failed:
            status = STATUS_COMPLETE
            error_message = None
        elif after_count > 0 or fetched:
            status = STATUS_PARTIAL
            if not error_message:
                error_message = "Provider crawl did not finish; coverage is partial."
        else:
            status = STATUS_FAILED
            if not error_message:
                error_message = "Provider crawl did not finish and no works were stored."

        await self._upsert_state(
            group,
            stored_work_count=after_count,
            provider_work_count=expected_total or len(fetched) or None,
            status=status,
            error_message=error_message,
            mark_attempt=True,
            mark_success=status == STATUS_COMPLETE,
        )
        await self.session.commit()

        stat = {
            "canonical_author_id": str(group.canonical_author_id),
            "provider": group.provider,
            "display_name": display_name,
            "stored_work_count_before": before_count,
            "existing_links_repaired": repaired,
            "fetched_work_count": len(fetched),
            "new_works": new_works,
            "stored_work_count_after": after_count,
            "status": status,
            "network_skipped": False,
            "error_message": error_message,
            "last_synced_at": datetime.now(timezone.utc).isoformat(),
        }
        if after_count == 0:
            logger.warning(
                "author_work_sync_no_coverage author=%s provider=%s status=%s",
                group.canonical_author_id,
                group.provider,
                status,
            )
        self._log_stats(stat, started)
        return stat

    async def _mark_group_incomplete(
        self,
        group: SyncProviderGroup,
        *,
        display_name: str,
        status: str,
        error_message: str,
        stored_work_count: int,
    ) -> dict[str, Any]:
        await self._upsert_state(
            group,
            stored_work_count=stored_work_count,
            provider_work_count=None,
            status=status,
            error_message=error_message,
            mark_attempt=True,
            mark_success=False,
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
            "status": status,
            "network_skipped": True,
            "error_message": error_message,
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

    async def _fetch_provider_works(
        self,
        record: SyncProviderRecord,
        *,
        deadline: float | None = None,
        on_page: Callable[..., Awaitable[None]] | None = None,
        publications_total: int | None = None,
        base_processed: int = 0,
    ) -> FetchResult:
        if record.provider == "openalex":
            if not self.settings.openalex_configured:
                raise OpenAlexApiError("OpenAlex is not configured.", status_code=503)
            return await self._fetch_openalex_works(
                record,
                deadline=deadline,
                on_page=on_page,
                publications_total=publications_total,
                base_processed=base_processed,
            )
        if record.provider == "arxiv":
            if not self.settings.arxiv_configured:
                raise ArxivApiError("arXiv is not configured.", status_code=503)
            return await self._fetch_arxiv_works(
                record,
                deadline=deadline,
                on_page=on_page,
                publications_total=publications_total,
                base_processed=base_processed,
            )
        return FetchResult(rows=[], finished=True)

    async def _fetch_openalex_works(
        self,
        record: SyncProviderRecord,
        *,
        deadline: float | None = None,
        on_page: Callable[..., Awaitable[None]] | None = None,
        publications_total: int | None = None,
        base_processed: int = 0,
    ) -> FetchResult:
        cursor: str | None = "*"
        rows: list[dict[str, Any]] = []
        seen_work_ids: set[str] = set()
        finished = True
        error_message: str | None = None
        while cursor is not None:
            if _deadline_exceeded(deadline):
                finished = False
                error_message = "Sync timed out while fetching OpenAlex publications."
                break
            page = await search_works_by_author_ids(
                author_id_groups=[[record.provider_author_id]],
                limit=SYNC_BATCH_SIZE,
                cursor=cursor,
            )
            for row in list(page.get("results") or []):
                if not isinstance(row, dict):
                    continue
                work_id = str(row.get("openalex_id") or row.get("source_id") or row.get("id") or "")
                if work_id and work_id in seen_work_ids:
                    continue
                if work_id:
                    seen_work_ids.add(work_id)
                rows.append(row)
            if on_page is not None:
                await on_page(
                    publications_processed=base_processed + len(rows),
                    publications_total=publications_total or record.works_count,
                    sync_status=STATUS_PARTIAL,
                    phase="syncing",
                )
            if page.get("has_more") and page.get("next_cursor"):
                cursor = str(page.get("next_cursor"))
            else:
                cursor = None
        return FetchResult(rows=rows, finished=finished, error_message=error_message)

    async def _fetch_arxiv_works(
        self,
        record: SyncProviderRecord,
        *,
        deadline: float | None = None,
        on_page: Callable[..., Awaitable[None]] | None = None,
        publications_total: int | None = None,
        base_processed: int = 0,
    ) -> FetchResult:
        cursor: str | None = None
        rows: list[dict[str, Any]] = []
        seen_work_ids: set[str] = set()
        finished = True
        error_message: str | None = None
        while True:
            if _deadline_exceeded(deadline):
                finished = False
                error_message = "Sync timed out while fetching arXiv publications."
                break
            page = await search_arxiv_publications_by_authors(
                author_names=[record.display_name],
                limit=SYNC_BATCH_SIZE,
                cursor=cursor,
            )
            for row in list(page.get("results") or []):
                if not isinstance(row, dict):
                    continue
                work_id = str(row.get("source_id") or row.get("arxiv_id") or row.get("id") or "")
                if work_id and work_id in seen_work_ids:
                    continue
                if work_id:
                    seen_work_ids.add(work_id)
                rows.append(row)
            if on_page is not None:
                await on_page(
                    publications_processed=base_processed + len(rows),
                    publications_total=publications_total or record.works_count,
                    sync_status=STATUS_PARTIAL,
                    phase="syncing",
                )
            if page.get("has_more") and page.get("next_cursor"):
                cursor = str(page.get("next_cursor"))
            else:
                break
        return FetchResult(rows=rows, finished=finished, error_message=error_message)

    async def _persist_fetched_works(
        self,
        record: SyncProviderRecord,
        rows: list[dict[str, Any]],
        *,
        on_progress: Callable[..., Awaitable[None]] | None = None,
        publications_total: int | None = None,
        base_processed: int = 0,
    ) -> int:
        new_works = 0
        for start in range(0, len(rows), SYNC_BATCH_SIZE):
            batch = rows[start : start + SYNC_BATCH_SIZE]
            persistence = WorkPersistenceService(self.session)
            for row in batch:
                candidate = candidate_from_provider_result(row, provider=record.provider)
                if candidate is None:
                    continue
                _ensure_selected_provider_author(candidate.raw_metadata, record)
                canonical, created = await persistence.resolve_candidate(candidate)
                if created:
                    new_works += 1
                if not created and not await self._has_author_authorship_link(
                    canonical_work_id=canonical.id,
                    record=record,
                ):
                    await WorkPersistenceRepository(self.session).replace_work_authorships(
                        canonical_work_id=canonical.id,
                        provider=record.provider,
                        provider_work_id=candidate.provider_work_id,
                        raw_metadata=candidate.raw_metadata,
                    )
                await WorkPersistenceRepository(self.session).ensure_author_work(
                    provider_record_id=record.id,
                    provider_work_id=candidate.provider_work_id,
                    provider=record.provider,
                    title=candidate.title,
                    publication_year=candidate.publication_year,
                )
            await self.session.commit()
            if on_progress is not None:
                await on_progress(
                    publications_processed=base_processed + start + len(batch),
                    publications_total=publications_total or record.works_count,
                    sync_status=STATUS_PARTIAL,
                    phase="syncing",
                )
        return new_works

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
            )
            self.session.add(state)
        else:
            if mark_attempt:
                state.last_attempted_at = now
            if mark_success:
                state.last_synced_at = now
                state.last_successful_synced_at = now
            elif status in {STATUS_PARTIAL, STATUS_FAILED, STATUS_STALE}:
                # Keep last_successful_synced_at; refresh last_synced_at only on success.
                pass
            state.stored_work_count = stored_work_count
            state.provider_work_count = provider_work_count
            state.status = status
            state.error_message = error_message
        await self.session.flush()

    async def _stored_work_count(self, canonical_author_id: uuid.UUID) -> int:
        return int(
            (
                await self.session.execute(
                    select(func.count(func.distinct(WorkAuthorship.canonical_work_id))).where(
                        WorkAuthorship.canonical_author_id == canonical_author_id
                    )
                )
            ).scalar_one()
            or 0
        )

    def _log_stats(self, stat: dict[str, Any], started: float) -> None:
        logger.info(
            "author_work_sync_stats=%s elapsed_ms=%.2f",
            stat,
            (time.perf_counter() - started) * 1000,
        )


def _deadline_exceeded(deadline: float | None) -> bool:
    return deadline is not None and time.monotonic() >= deadline


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
        return
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
