"""Selected-author work coverage synchronization.

`work_authorships.canonical_author_id` is the authoritative author-to-work
relationship. `author_works` is maintained as a derived provider-work index for
existing author identity overlap code.
"""

from __future__ import annotations

import asyncio
import logging
import time
import uuid
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

_sync_locks: dict[str, asyncio.Lock] = {}
_sync_locks_guard = asyncio.Lock()


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


async def _lock_for_key(key: str) -> asyncio.Lock:
    async with _sync_locks_guard:
        lock = _sync_locks.get(key)
        if lock is None:
            lock = asyncio.Lock()
            _sync_locks[key] = lock
        return lock


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
    ) -> list[dict[str, Any]]:
        records = await self._load_selected_provider_records(authors)
        groups = self._group_provider_records(records)
        deadline = (
            time.monotonic() + max(float(timeout_seconds), 0.0)
            if timeout_seconds is not None
            else None
        )
        stats: list[dict[str, Any]] = []
        for group in groups:
            if _deadline_exceeded(deadline):
                stat = {
                    "canonical_author_id": str(group.canonical_author_id),
                    "provider": group.provider,
                    "stored_work_count_before": 0,
                    "existing_links_repaired": 0,
                    "fetched_work_count": 0,
                    "new_works": 0,
                    "stored_work_count_after": 0,
                    "status": "skipped_timeout",
                    "last_synced_at": None,
                }
                logger.info(
                    "author_work_sync skipped_timeout author=%s provider=%s",
                    group.canonical_author_id,
                    group.provider,
                )
                stats.append(stat)
                continue
            key = "|".join(
                [
                    str(group.canonical_author_id),
                    group.provider,
                ]
            )
            lock = await _lock_for_key(key)
            async with lock:
                stats.append(await self._sync_provider_group(group, deadline=deadline))
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
                records=tuple(
                    sorted(rows, key=lambda row: row.provider_author_id)
                ),
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

    async def _sync_provider_group(
        self,
        group: SyncProviderGroup,
        *,
        deadline: float | None = None,
    ) -> dict[str, Any]:
        started = time.perf_counter()
        before_count = await self._stored_work_count(group.canonical_author_id)
        repaired = 0
        for record in group.records:
            repaired += await self._repair_existing_links(record)
        after_repair_count = await self._stored_work_count(group.canonical_author_id)
        await self.session.commit()

        state = await self._load_state(group)
        if self._state_is_fresh(state):
            # Fresh cache reuse: do not rewrite last_synced_at.
            stat = {
                "canonical_author_id": str(group.canonical_author_id),
                "provider": group.provider,
                "stored_work_count_before": before_count,
                "existing_links_repaired": repaired,
                "fetched_work_count": 0,
                "new_works": 0,
                "stored_work_count_after": after_repair_count,
                "status": "fresh",
                "last_synced_at": (
                    state.last_synced_at.isoformat()
                    if state and state.last_synced_at
                    else None
                ),
            }
            self._log_stats(stat, started)
            return stat

        fetched: list[dict[str, Any]] = []
        fetch_status = "success"
        new_works = 0
        for record in group.records:
            if _deadline_exceeded(deadline):
                fetch_status = "timeout"
                logger.info(
                    "author_work_sync fetch_timeout author=%s provider=%s",
                    group.canonical_author_id,
                    group.provider,
                )
                break
            try:
                record_rows = await self._fetch_provider_works(record, deadline=deadline)
            except Exception as exc:
                fetch_status = "provider_failed"
                logger.warning(
                    "author_work_sync provider_failed author=%s provider=%s "
                    "provider_author_id=%s error=%s",
                    record.canonical_author_id,
                    record.provider,
                    record.provider_author_id,
                    exc,
                )
                continue
            if _deadline_exceeded(deadline) and fetch_status == "success":
                fetch_status = "timeout"
                logger.info(
                    "author_work_sync fetch_timeout author=%s provider=%s",
                    group.canonical_author_id,
                    group.provider,
                )
            fetched.extend(record_rows)
            if record_rows:
                new_works += await self._persist_fetched_works(record, record_rows)
                repaired += await self._repair_existing_links(record)

        after_count = await self._stored_work_count(group.canonical_author_id)
        status = "success" if fetch_status == "success" else fetch_status
        await self._upsert_state(
            group,
            stored_work_count=after_count,
            provider_work_count=sum(
                record.works_count or 0 for record in group.records
            )
            or len(fetched)
            or None,
            status=status,
        )
        await self.session.commit()

        stat = {
            "canonical_author_id": str(group.canonical_author_id),
            "provider": group.provider,
            "stored_work_count_before": before_count,
            "existing_links_repaired": repaired,
            "fetched_work_count": len(fetched),
            "new_works": new_works,
            "stored_work_count_after": after_count,
            "status": status,
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
    ) -> list[dict[str, Any]]:
        if record.provider == "openalex":
            if not self.settings.openalex_configured:
                raise OpenAlexApiError("OpenAlex is not configured.", status_code=503)
            return await self._fetch_openalex_works(record, deadline=deadline)
        if record.provider == "arxiv":
            if not self.settings.arxiv_configured:
                raise ArxivApiError("arXiv is not configured.", status_code=503)
            return await self._fetch_arxiv_works(record, deadline=deadline)
        return []

    async def _fetch_openalex_works(
        self,
        record: SyncProviderRecord,
        *,
        deadline: float | None = None,
    ) -> list[dict[str, Any]]:
        cursor: str | None = "*"
        rows: list[dict[str, Any]] = []
        seen_work_ids: set[str] = set()
        while cursor is not None:
            if _deadline_exceeded(deadline):
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
            if page.get("has_more") and page.get("next_cursor"):
                cursor = str(page.get("next_cursor"))
            else:
                cursor = None
        return rows

    async def _fetch_arxiv_works(
        self,
        record: SyncProviderRecord,
        *,
        deadline: float | None = None,
    ) -> list[dict[str, Any]]:
        cursor: str | None = None
        rows: list[dict[str, Any]] = []
        seen_work_ids: set[str] = set()
        while True:
            if _deadline_exceeded(deadline):
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
            if page.get("has_more") and page.get("next_cursor"):
                cursor = str(page.get("next_cursor"))
            else:
                break
        return rows

    async def _persist_fetched_works(
        self,
        record: SyncProviderRecord,
        rows: list[dict[str, Any]],
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

    def _state_is_fresh(self, state: AuthorWorkSyncState | None) -> bool:
        if state is None or state.status != "success" or state.last_synced_at is None:
            return False
        synced_at = state.last_synced_at
        if synced_at.tzinfo is None:
            synced_at = synced_at.replace(tzinfo=timezone.utc)
        age = (datetime.now(timezone.utc) - synced_at).total_seconds()
        return age < self.settings.author_work_sync_ttl_seconds

    async def _upsert_state(
        self,
        group: SyncProviderGroup,
        *,
        stored_work_count: int,
        provider_work_count: int | None,
        status: str,
    ) -> None:
        state = await self._load_state(group)
        now = datetime.now(timezone.utc)
        if state is None:
            state = AuthorWorkSyncState(
                id=uuid.uuid4(),
                canonical_author_id=group.canonical_author_id,
                provider=group.provider,
                last_synced_at=now,
                stored_work_count=stored_work_count,
                provider_work_count=provider_work_count,
                status=status,
            )
            self.session.add(state)
        else:
            state.last_synced_at = now
            state.stored_work_count = stored_work_count
            state.provider_work_count = provider_work_count
            state.status = status
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
