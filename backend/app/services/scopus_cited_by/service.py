"""Scopus cited-by sync: resolve IDs, paginate REF(), persist citing works.

HTTP runs outside SQLite write transactions. Pagination never holds a
transaction across network calls. Per-work failures do not abort a batch.
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from datetime import datetime, timedelta, timezone
from typing import Iterable

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.db.models.scopus_cited_by import (
    ScopusCitationLink,
    ScopusCitedBySync,
    ScopusCitingWork,
)
from app.db.models.work_persistence import CanonicalWork
from app.integrations.elsevier.cited_by import (
    CitingWorkRecord,
    ScopusWorkIds,
    citing_work_dedupe_key,
    extract_numeric_scopus_id,
    fetch_citing_page,
    resolve_scopus_ids_for_doi,
)
from app.integrations.elsevier.client import ElsevierApiError, ElsevierClient, elsevier_configured
from app.services.work_persistence.normalization import normalize_doi

logger = logging.getLogger(__name__)

FRESH_STATUSES = frozenset({"success", "partial", "not_found", "unavailable"})
NEGATIVE_STATUSES = frozenset({"not_found", "unavailable", "error"})
PERSIST_BATCH_SIZE = 50

_http_during_transaction = False


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def reset_http_during_transaction_flag() -> None:
    global _http_during_transaction
    _http_during_transaction = False


def http_ran_during_transaction() -> bool:
    return _http_during_transaction


def _ttl_for_status(status: str) -> timedelta:
    settings = get_settings()
    if status in NEGATIVE_STATUSES:
        days = settings.scopus_cited_by_negative_ttl_days
    else:
        days = settings.scopus_cited_by_success_ttl_days
    return timedelta(days=max(int(days), 1))


def _aware(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value


def cache_is_fresh(row: ScopusCitedBySync | None, *, now: datetime | None = None) -> bool:
    if row is None or row.status not in FRESH_STATUSES:
        return False
    expires = _aware(row.expires_at)
    if expires is None:
        return False
    return expires > (now or utc_now())


class ScopusCitedByService:
    def __init__(
        self,
        session: AsyncSession,
        *,
        client: ElsevierClient | None = None,
    ) -> None:
        self.session = session
        self._client = client or ElsevierClient()

    async def _commit_if_needed(self) -> None:
        if self.session.in_transaction():
            await self.session.commit()

    def _mark_http(self) -> None:
        global _http_during_transaction
        if self.session.in_transaction():
            _http_during_transaction = True
            logger.error("scopus_cited_by_http_during_sqlite_transaction")

    async def get_sync(self, canonical_work_id: uuid.UUID) -> ScopusCitedBySync | None:
        result = await self.session.execute(
            select(ScopusCitedBySync).where(
                ScopusCitedBySync.canonical_work_id == canonical_work_id
            )
        )
        return result.scalar_one_or_none()

    async def _get_or_create_sync(self, canonical_work_id: uuid.UUID) -> ScopusCitedBySync:
        row = await self.get_sync(canonical_work_id)
        if row is not None:
            return row
        row = ScopusCitedBySync(
            id=uuid.uuid4(),
            canonical_work_id=canonical_work_id,
            status="never",
        )
        self.session.add(row)
        await self.session.flush()
        return row

    async def _save_sync(
        self,
        row: ScopusCitedBySync,
        *,
        status: str,
        error_message: str | None = None,
        fetched_result_count: int | None = None,
        scopus_id: str | None = None,
        eid: str | None = None,
        citedby_count: int | None = None,
        touch_synced: bool = True,
    ) -> ScopusCitedBySync:
        now = utc_now()
        if scopus_id:
            row.scopus_id = extract_numeric_scopus_id(scopus_id) or scopus_id
        if eid:
            row.eid = eid
        if citedby_count is not None:
            row.citedby_count = citedby_count
        row.status = status
        if fetched_result_count is not None:
            row.fetched_result_count = fetched_result_count
        row.error_message = error_message
        if touch_synced:
            row.last_synced_at = now
            row.expires_at = now + _ttl_for_status(status)
        row.updated_at = now
        await self.session.commit()
        return row

    async def sync_canonical_works(
        self,
        canonical_work_ids: Iterable[uuid.UUID],
    ) -> list[ScopusCitedBySync]:
        unique: list[uuid.UUID] = []
        seen: set[uuid.UUID] = set()
        for value in canonical_work_ids:
            if value in seen:
                continue
            seen.add(value)
            unique.append(value)
        if not unique:
            return []

        concurrency = max(int(get_settings().scopus_cited_by_concurrency), 1)
        semaphore = asyncio.Semaphore(concurrency)
        results: dict[uuid.UUID, ScopusCitedBySync] = {}

        async def _one(work_id: uuid.UUID) -> None:
            async with semaphore:
                try:
                    row = await self.sync_canonical_work(work_id)
                    if row is not None:
                        results[work_id] = row
                except Exception as exc:  # noqa: BLE001 — one work must not fail the batch
                    logger.warning(
                        "scopus_cited_by_work_failed canonical_work_id=%s error=%s",
                        work_id,
                        type(exc).__name__,
                    )
                    try:
                        row = await self._get_or_create_sync(work_id)
                        await self._save_sync(
                            row,
                            status="error",
                            error_message=str(exc)[:2000] or type(exc).__name__,
                        )
                        results[work_id] = row
                    except Exception:
                        logger.exception(
                            "scopus_cited_by_error_persist_failed canonical_work_id=%s",
                            work_id,
                        )

        await asyncio.gather(*[_one(work_id) for work_id in unique])
        ordered: list[ScopusCitedBySync] = []
        for work_id in unique:
            row = results.get(work_id)
            if row is None:
                row = await self.get_sync(work_id)
            if row is not None:
                ordered.append(row)
        return ordered

    async def sync_canonical_work(self, canonical_work_id: uuid.UUID) -> ScopusCitedBySync:
        await self._commit_if_needed()
        work = await self.session.get(CanonicalWork, canonical_work_id)
        row = await self._get_or_create_sync(canonical_work_id)
        await self._commit_if_needed()

        if cache_is_fresh(row):
            return row

        if work is None:
            return await self._save_sync(row, status="error", error_message="Canonical work not found.")

        if not elsevier_configured():
            return await self._save_sync(
                row,
                status="unavailable",
                error_message="Elsevier API key is not configured.",
            )

        doi = normalize_doi(work.doi)
        if not doi and not row.scopus_id:
            return await self._save_sync(
                row,
                status="not_found",
                error_message="Canonical work has no DOI to resolve in Scopus.",
            )

        try:
            ids = await self._resolve_ids(row, doi)
        except ElsevierApiError as exc:
            status = "unavailable" if exc.entitlement else "error"
            return await self._save_sync(row, status=status, error_message=str(exc)[:2000])

        if not ids.scopus_id:
            return await self._save_sync(
                row,
                status="not_found",
                error_message="No Scopus ID found for DOI.",
                scopus_id=ids.scopus_id,
                eid=ids.eid,
                citedby_count=ids.citedby_count,
            )

        row.scopus_id = ids.scopus_id
        row.eid = ids.eid or row.eid
        if ids.citedby_count is not None:
            row.citedby_count = ids.citedby_count
        await self.session.commit()

        try:
            fetched, truncated = await self._paginate_citing_works(
                canonical_work_id=canonical_work_id,
                cited_scopus_id=ids.scopus_id,
            )
        except ElsevierApiError as exc:
            status = "unavailable" if exc.entitlement else "error"
            return await self._save_sync(
                row,
                status=status,
                error_message=str(exc)[:2000],
                scopus_id=ids.scopus_id,
                eid=ids.eid,
                citedby_count=ids.citedby_count,
            )

        status = "partial" if truncated else "success"
        error = "Cited-by result set exceeded the configured maximum." if truncated else None
        return await self._save_sync(
            row,
            status=status,
            error_message=error,
            fetched_result_count=fetched,
            scopus_id=ids.scopus_id,
            eid=ids.eid,
            citedby_count=ids.citedby_count,
        )

    async def _resolve_ids(self, row: ScopusCitedBySync, doi: str | None) -> ScopusWorkIds:
        if row.scopus_id:
            return ScopusWorkIds(
                scopus_id=extract_numeric_scopus_id(row.scopus_id) or row.scopus_id,
                eid=row.eid,
                citedby_count=row.citedby_count,
            )
        if not doi:
            return ScopusWorkIds()
        self._mark_http()
        ids, _source = await resolve_scopus_ids_for_doi(doi, client=self._client)
        return ids

    async def _paginate_citing_works(
        self,
        *,
        canonical_work_id: uuid.UUID,
        cited_scopus_id: str,
    ) -> tuple[int, bool]:
        settings = get_settings()
        page_size = max(int(settings.scopus_cited_by_page_size), 1)
        max_results = max(int(settings.scopus_cited_by_max_results), page_size)
        start = 0
        stored = 0
        truncated = False
        seen_keys: set[str] = set()

        while start < max_results:
            self._mark_http()
            response, page = await fetch_citing_page(
                cited_scopus_id,
                start=start,
                count=page_size,
                client=self._client,
            )
            if response.status_code in {401, 403}:
                raise ElsevierApiError(
                    f"Elsevier Scopus Search denied ({response.status_code}).",
                    status_code=response.status_code,
                    entitlement=True,
                )
            if response.status_code == 404:
                break
            if response.status_code != 200:
                raise ElsevierApiError(
                    f"Elsevier Scopus Search failed ({response.status_code}).",
                    status_code=response.status_code,
                    retryable=response.status_code == 429 or response.status_code >= 500,
                )

            unique_page: list[CitingWorkRecord] = []
            for record in page.entries:
                key = citing_work_dedupe_key(record)
                if key is None:
                    continue
                if key in seen_keys:
                    continue
                seen_keys.add(key)
                unique_page.append(record)

            stored += await self._persist_citing_batch(
                unique_page,
                cited_canonical_work_id=canonical_work_id,
                cited_scopus_id=cited_scopus_id,
            )

            returned = len(page.entries)
            next_start = start + (page.items_per_page or returned or page_size)
            if returned == 0:
                break
            if next_start >= page.total_results:
                break
            if next_start >= max_results and page.total_results > max_results:
                truncated = True
                break
            start = next_start

        return stored, truncated

    async def _persist_citing_batch(
        self,
        records: list[CitingWorkRecord],
        *,
        cited_canonical_work_id: uuid.UUID,
        cited_scopus_id: str,
    ) -> int:
        if not records:
            await self._commit_if_needed()
            return 0
        persisted = 0
        for offset in range(0, len(records), PERSIST_BATCH_SIZE):
            chunk = records[offset : offset + PERSIST_BATCH_SIZE]
            persisted += await self._upsert_chunk(
                chunk,
                cited_canonical_work_id=cited_canonical_work_id,
                cited_scopus_id=cited_scopus_id,
            )
        return persisted

    async def _upsert_chunk(
        self,
        records: list[CitingWorkRecord],
        *,
        cited_canonical_work_id: uuid.UUID,
        cited_scopus_id: str,
    ) -> int:
        scopus_ids = [item.scopus_id for item in records if item.scopus_id]
        eids = [item.eid for item in records if item.eid]
        dois = [item.normalized_doi for item in records if item.normalized_doi]
        clauses = []
        if scopus_ids:
            clauses.append(ScopusCitingWork.scopus_id.in_(scopus_ids))
        if eids:
            clauses.append(ScopusCitingWork.eid.in_(eids))
        if dois:
            clauses.append(ScopusCitingWork.normalized_doi.in_(dois))

        existing_by_scopus: dict[str, ScopusCitingWork] = {}
        existing_by_eid: dict[str, ScopusCitingWork] = {}
        existing_by_doi: dict[str, ScopusCitingWork] = {}
        if clauses:
            result = await self.session.execute(
                select(ScopusCitingWork).where(or_(*clauses))
            )
            for row in result.scalars().all():
                if row.scopus_id:
                    existing_by_scopus[row.scopus_id] = row
                if row.eid:
                    existing_by_eid[row.eid] = row
                if row.normalized_doi:
                    existing_by_doi[row.normalized_doi] = row

        citing_ids: list[uuid.UUID] = []
        for record in records:
            row = None
            if record.scopus_id:
                row = existing_by_scopus.get(record.scopus_id)
            if row is None and record.eid:
                row = existing_by_eid.get(record.eid)
            if row is None and record.normalized_doi:
                row = existing_by_doi.get(record.normalized_doi)
            if row is None:
                row = ScopusCitingWork(id=uuid.uuid4())
                self.session.add(row)
            _apply_citing_metadata(row, record)
            if row.scopus_id:
                existing_by_scopus[row.scopus_id] = row
            if row.eid:
                existing_by_eid[row.eid] = row
            if row.normalized_doi:
                existing_by_doi[row.normalized_doi] = row
            citing_ids.append(row.id)

        await self.session.flush()

        if citing_ids:
            link_result = await self.session.execute(
                select(ScopusCitationLink).where(
                    ScopusCitationLink.cited_canonical_work_id == cited_canonical_work_id,
                    ScopusCitationLink.citing_work_id.in_(citing_ids),
                )
            )
            have = {link.citing_work_id for link in link_result.scalars().all()}
            for citing_id in citing_ids:
                if citing_id in have:
                    continue
                self.session.add(
                    ScopusCitationLink(
                        id=uuid.uuid4(),
                        citing_work_id=citing_id,
                        cited_canonical_work_id=cited_canonical_work_id,
                        cited_scopus_id=cited_scopus_id,
                    )
                )
                have.add(citing_id)

        await self.session.commit()
        return len(records)


def _apply_citing_metadata(row: ScopusCitingWork, record: CitingWorkRecord) -> None:
    now = utc_now()
    if record.scopus_id:
        row.scopus_id = record.scopus_id
    if record.eid:
        row.eid = record.eid
    elif record.scopus_id and not row.eid:
        row.eid = f"2-s2.0-{record.scopus_id}"
    if record.doi:
        row.doi = record.doi
    if record.normalized_doi:
        row.normalized_doi = record.normalized_doi
    if record.title:
        row.title = record.title[:2048]
    if record.cover_date:
        row.cover_date = record.cover_date[:32]
    if record.publication_year is not None:
        row.publication_year = record.publication_year
    if record.source_title:
        row.source_title = record.source_title[:1024]
    if record.affiliations:
        row.affiliations = record.affiliations
    row.updated_at = now
