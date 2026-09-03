"""Repository helpers for data update jobs."""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import delete, distinct, func, literal, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import (
    AuthorProfile,
    AuthorWorkSyncState,
    CanonicalAuthor,
    CanonicalAuthorInstitution,
    CanonicalWork,
    DataUpdateJob,
    DataUpdateJobRecord,
    ProviderAuthorRecord,
    ProviderSearchCache,
    ProviderWorkRecord,
    RefreshSubjectState,
    SearchSession,
    SavedSearch,
    WorkAuthorship,
    WorkGrantMatch,
)


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class DataUpdaterRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def create_job(
        self,
        *,
        mode: str,
        dataset: str | None,
        record_ids: list[str] | None,
        metadata: dict[str, Any] | None = None,
    ) -> DataUpdateJob:
        job = DataUpdateJob(
            id=uuid.uuid4(),
            mode=mode,
            dataset=dataset,
            status="queued",
            requested_record_ids=record_ids or None,
            metadata_=metadata,
        )
        self.session.add(job)
        await self.session.flush()
        return job

    async def get_job(self, job_id: str | uuid.UUID) -> DataUpdateJob | None:
        try:
            row_id = job_id if isinstance(job_id, uuid.UUID) else uuid.UUID(str(job_id))
        except ValueError:
            return None
        return await self.session.get(DataUpdateJob, row_id)

    async def list_job_records(self, job_id: str | uuid.UUID) -> list[DataUpdateJobRecord]:
        try:
            row_id = job_id if isinstance(job_id, uuid.UUID) else uuid.UUID(str(job_id))
        except ValueError:
            return []
        rows = await self.session.execute(
            select(DataUpdateJobRecord)
            .where(DataUpdateJobRecord.job_id == row_id)
            .order_by(DataUpdateJobRecord.created_at.desc())
        )
        return list(rows.scalars().all())

    async def completed_record_keys(self, job_id: str | uuid.UUID) -> set[tuple[str, str]]:
        try:
            row_id = job_id if isinstance(job_id, uuid.UUID) else uuid.UUID(str(job_id))
        except ValueError:
            return set()
        rows = await self.session.execute(
            select(DataUpdateJobRecord.dataset, DataUpdateJobRecord.record_id).where(
                DataUpdateJobRecord.job_id == row_id,
                DataUpdateJobRecord.status.in_(["updated", "unchanged"]),
            )
        )
        return {(str(dataset), str(record_id)) for dataset, record_id in rows.all()}

    async def mark_job_started(self, job: DataUpdateJob, *, total: int) -> None:
        now = utc_now()
        job.status = "running"
        job.started_at = job.started_at or now
        job.updated_at = now
        job.total_records = max(job.total_records or 0, total)
        await self.session.flush()

    async def mark_job_completed(self, job: DataUpdateJob, *, status: str = "succeeded") -> None:
        now = utc_now()
        job.status = status
        job.completed_at = now
        job.updated_at = now
        await self.session.flush()

    async def request_job_pause(self, job: DataUpdateJob) -> None:
        job.status = "pause_requested"
        job.updated_at = utc_now()
        await self.session.flush()

    async def mark_job_paused(self, job: DataUpdateJob) -> None:
        job.status = "paused"
        job.updated_at = utc_now()
        await self.session.flush()

    async def request_job_cancel(self, job: DataUpdateJob) -> None:
        job.status = "cancel_requested"
        job.updated_at = utc_now()
        await self.session.flush()

    async def mark_job_cancelled(self, job: DataUpdateJob) -> None:
        now = utc_now()
        job.status = "cancelled"
        job.completed_at = now
        job.updated_at = now
        await self.session.flush()

    async def mark_job_failed(self, job: DataUpdateJob, error: str) -> None:
        now = utc_now()
        job.status = "failed"
        job.error = error
        job.completed_at = now
        job.updated_at = now
        await self.session.flush()

    async def add_record_result(
        self,
        *,
        job: DataUpdateJob,
        dataset: str,
        record_id: str,
        status: str,
        source: str | None = None,
        message: str | None = None,
        retry_count: int = 0,
    ) -> None:
        self.session.add(
            DataUpdateJobRecord(
                id=uuid.uuid4(),
                job_id=job.id,
                dataset=dataset,
                record_id=record_id,
                source=source,
                status=status,
                message=message,
                retry_count=retry_count,
            )
        )
        job.processed_records += 1
        if status == "updated":
            job.updated_count += 1
        elif status == "unchanged":
            job.unchanged_count += 1
        elif status == "retrying":
            job.retrying_count += 1
        elif status == "failed":
            job.failed_count += 1
        job.updated_at = utc_now()
        await self.session.flush()

    async def upsert_subject_state(
        self,
        *,
        dataset: str,
        record_id: str,
        source: str | None,
        status: str,
        error: str | None = None,
        retry_count: int = 0,
    ) -> None:
        row = (
            await self.session.execute(
                select(RefreshSubjectState).where(
                    RefreshSubjectState.dataset == dataset,
                    RefreshSubjectState.record_id == record_id,
                )
            )
        ).scalar_one_or_none()
        now = utc_now()
        if row is None:
            row = RefreshSubjectState(
                id=uuid.uuid4(),
                dataset=dataset,
                record_id=record_id,
            )
            self.session.add(row)
        row.source = source or row.source
        row.last_updated = now
        row.refresh_status = status
        row.last_error = error
        row.retry_count = retry_count
        row.updated_at = now
        if status in {"updated", "unchanged"}:
            row.last_successful_refresh = now
            row.retry_count = 0
        await self.session.flush()

    async def count_refresh_targets(self, dataset: str) -> int:
        stmt = self._target_query(dataset, stale_cutoff=None, record_ids=None, count=True)
        return int((await self.session.execute(stmt)).scalar_one() or 0)

    async def count_stale_targets(self, dataset: str, ttl_seconds: int | None) -> int:
        cutoff = utc_now() - timedelta(seconds=ttl_seconds or 0)
        stmt = self._target_query(dataset, stale_cutoff=cutoff, record_ids=None, count=True)
        return int((await self.session.execute(stmt)).scalar_one() or 0)

    async def search_user_refresh_targets(self, query: str, *, limit: int = 8) -> list[dict[str, Any]]:
        normalized = " ".join(query.split())
        if len(normalized) < 2:
            return []
        pattern = f"%{normalized.lower()}%"
        per_type = max(1, limit)
        items: list[dict[str, Any]] = []

        author_rows = await self.session.execute(
            select(
                CanonicalAuthor.id,
                CanonicalAuthor.preferred_name,
                AuthorProfile.updated_at,
                func.count(CanonicalAuthorInstitution.id).label("institution_count"),
            )
            .outerjoin(AuthorProfile, AuthorProfile.canonical_author_id == CanonicalAuthor.id)
            .outerjoin(
                CanonicalAuthorInstitution,
                CanonicalAuthorInstitution.canonical_author_id == CanonicalAuthor.id,
            )
            .where(func.lower(CanonicalAuthor.preferred_name).like(pattern))
            .group_by(CanonicalAuthor.id, CanonicalAuthor.preferred_name, AuthorProfile.updated_at)
            .order_by(CanonicalAuthor.preferred_name)
            .limit(per_type)
        )
        for row in author_rows.all():
            subtitle = "Author"
            if row.institution_count:
                subtitle = f"Author · {row.institution_count} affiliation(s)"
            items.append(
                {
                    "id": str(row.id),
                    "type": "author",
                    "title": row.preferred_name,
                    "subtitle": subtitle,
                    "last_updated": row.updated_at,
                }
            )

        work_rows = await self.session.execute(
            select(CanonicalWork.id, CanonicalWork.title, CanonicalWork.publication_year, CanonicalWork.updated_at)
            .where(func.lower(CanonicalWork.title).like(pattern))
            .order_by(CanonicalWork.updated_at.desc())
            .limit(per_type)
        )
        for row in work_rows.all():
            subtitle = "Publication"
            if row.publication_year:
                subtitle = f"Publication · {row.publication_year}"
            items.append(
                {
                    "id": str(row.id),
                    "type": "publication",
                    "title": row.title,
                    "subtitle": subtitle,
                    "last_updated": row.updated_at,
                }
            )

        institution_rows = await self.session.execute(
            select(
                CanonicalAuthorInstitution.institution_key,
                func.max(CanonicalAuthorInstitution.institution_name).label("institution_name"),
                func.max(CanonicalAuthorInstitution.country_code).label("country_code"),
                func.max(CanonicalAuthorInstitution.updated_at).label("updated_at"),
                func.count(distinct(CanonicalAuthorInstitution.canonical_author_id)).label("author_count"),
            )
            .where(
                or_(
                    func.lower(CanonicalAuthorInstitution.institution_name).like(pattern),
                    func.lower(CanonicalAuthorInstitution.institution_key).like(pattern),
                )
            )
            .group_by(CanonicalAuthorInstitution.institution_key)
            .order_by(func.max(CanonicalAuthorInstitution.updated_at).desc())
            .limit(per_type)
        )
        for row in institution_rows.all():
            title = row.institution_name or row.institution_key
            suffix = f" · {row.country_code}" if row.country_code else ""
            items.append(
                {
                    "id": row.institution_key,
                    "type": "institution",
                    "title": title,
                    "subtitle": f"Institution{suffix} · {row.author_count} author(s)",
                    "last_updated": row.updated_at,
                }
            )

        return items[:limit]

    async def list_saved_search_options(self) -> list[SavedSearch]:
        stmt = select(SavedSearch)
        rows = await self.session.execute(
            stmt.order_by(
                SavedSearch.is_pinned.desc(),
                func.coalesce(SavedSearch.last_viewed_at, SavedSearch.updated_at).desc(),
                SavedSearch.display_name.asc(),
            )
        )
        return list(rows.scalars().all())

    async def list_saved_searches(self) -> list[SavedSearch]:
        rows = await self.session.execute(
            select(SavedSearch).order_by(SavedSearch.updated_at.desc())
        )
        return list(rows.scalars().all())

    async def get_saved_search(
        self,
        saved_search_id: str | uuid.UUID,
    ) -> SavedSearch | None:
        try:
            row_id = saved_search_id if isinstance(saved_search_id, uuid.UUID) else uuid.UUID(str(saved_search_id))
        except ValueError:
            return None
        return await self.session.get(SavedSearch, row_id)

    async def author_ids_for_institution(self, institution_key: str) -> list[str]:
        rows = await self.session.execute(
            select(distinct(CanonicalAuthorInstitution.canonical_author_id)).where(
                CanonicalAuthorInstitution.institution_key == institution_key
            )
        )
        return [str(row[0]) for row in rows.all() if row[0]]

    async def publication_ids_for_authors(self, author_ids: list[str]) -> list[str]:
        if not author_ids:
            return []
        rows = await self.session.execute(
            select(distinct(WorkAuthorship.canonical_work_id)).where(
                WorkAuthorship.canonical_author_id.in_(author_ids)
            )
        )
        return [str(row[0]) for row in rows.all() if row[0]]

    async def publication_ids_for_grant(self, grant_number: str) -> list[str]:
        normalized = "".join(ch for ch in str(grant_number or "").lower() if ch.isalnum())
        if not normalized:
            return []
        rows = await self.session.execute(
            select(distinct(WorkGrantMatch.canonical_work_id)).where(
                WorkGrantMatch.normalized_grant_number == normalized
            )
        )
        return [str(row[0]) for row in rows.all() if row[0]]

    async def list_refresh_targets(
        self,
        dataset: str,
        *,
        ttl_seconds: int | None,
        record_ids: list[str] | None,
        stale_only: bool,
    ) -> list[dict[str, Any]]:
        cutoff = utc_now() - timedelta(seconds=ttl_seconds or 0) if stale_only else None
        stmt = self._target_query(dataset, stale_cutoff=cutoff, record_ids=record_ids, count=False)
        rows = (await self.session.execute(stmt)).all()
        return [
            {
                "record_id": str(row.record_id),
                "source": getattr(row, "source", None),
                "provider_record_id": str(getattr(row, "provider_record_id", "") or ""),
            }
            for row in rows
        ]

    def _target_query(
        self,
        dataset: str,
        *,
        stale_cutoff: datetime | None,
        record_ids: list[str] | None,
        count: bool,
    ):
        id_filter = set(record_ids or [])

        def columns(id_col, source_col=None, provider_record_id_col=None):
            selected = [
                id_col.label("record_id"),
                (source_col if source_col is not None else literal(None)).label("source"),
                (provider_record_id_col if provider_record_id_col is not None else literal(None)).label("provider_record_id"),
            ]
            return func.count(func.distinct(id_col)) if count else selected

        def apply_state(stmt, id_col):
            if stale_cutoff is None:
                return stmt
            stmt = stmt.outerjoin(
                RefreshSubjectState,
                (RefreshSubjectState.dataset == dataset)
                & (RefreshSubjectState.record_id == id_col),
            )
            return stmt.where(
                or_(
                    RefreshSubjectState.id.is_(None),
                    RefreshSubjectState.last_successful_refresh.is_(None),
                    RefreshSubjectState.last_successful_refresh < stale_cutoff,
                    RefreshSubjectState.refresh_status == "failed",
                )
            )

        if dataset in {"authors", "author_affiliations", "institutions"}:
            selected = columns(CanonicalAuthor.id, ProviderAuthorRecord.provider, ProviderAuthorRecord.id)
            stmt = (
                select(selected) if count else select(*selected)
            ).join(
                ProviderAuthorRecord,
                ProviderAuthorRecord.canonical_author_id == CanonicalAuthor.id,
            ).where(ProviderAuthorRecord.provider == "openalex")
            if id_filter:
                stmt = stmt.where(CanonicalAuthor.id.in_(id_filter))
            stmt = apply_state(stmt, CanonicalAuthor.id)
            if count:
                return stmt
            return stmt.group_by(CanonicalAuthor.id, ProviderAuthorRecord.provider, ProviderAuthorRecord.id)

        if dataset == "author_publications":
            selected = columns(CanonicalAuthor.id, ProviderAuthorRecord.provider, ProviderAuthorRecord.id)
            stmt = (
                select(selected) if count else select(*selected)
            ).join(
                ProviderAuthorRecord,
                ProviderAuthorRecord.canonical_author_id == CanonicalAuthor.id,
            ).where(ProviderAuthorRecord.provider.in_(["openalex", "arxiv"]))
            if id_filter:
                stmt = stmt.where(CanonicalAuthor.id.in_(id_filter))
            stmt = apply_state(stmt, CanonicalAuthor.id)
            if count:
                return stmt
            return stmt.group_by(CanonicalAuthor.id, ProviderAuthorRecord.provider, ProviderAuthorRecord.id)

        if dataset in {"publications", "publication_metadata", "citation_counts", "grant_funding"}:
            selected = columns(CanonicalWork.id, ProviderWorkRecord.provider, ProviderWorkRecord.id)
            stmt = (
                select(selected) if count else select(*selected)
            ).join(
                ProviderWorkRecord,
                ProviderWorkRecord.canonical_work_id == CanonicalWork.id,
            )
            if dataset in {"publication_metadata", "citation_counts", "grant_funding"}:
                stmt = stmt.where(ProviderWorkRecord.provider == "openalex")
            if id_filter:
                stmt = stmt.where(CanonicalWork.id.in_(id_filter))
            stmt = apply_state(stmt, CanonicalWork.id)
            if count:
                return stmt
            return stmt.group_by(CanonicalWork.id, ProviderWorkRecord.provider, ProviderWorkRecord.id)

        if dataset == "provider_search_cache":
            selected = columns(ProviderSearchCache.id, ProviderSearchCache.provider)
            stmt = select(selected) if count else select(*selected)
            if id_filter:
                stmt = stmt.where(ProviderSearchCache.id.in_(id_filter))
            if stale_cutoff is not None:
                stmt = stmt.where(ProviderSearchCache.expires_at <= utc_now())
            return stmt

        if dataset == "search_sessions":
            selected = columns(SearchSession.id, SearchSession.provider)
            stmt = select(selected) if count else select(*selected)
            if id_filter:
                stmt = stmt.where(SearchSession.id.in_(id_filter))
            if stale_cutoff is not None:
                stmt = stmt.where(SearchSession.expires_at <= utc_now())
            return stmt

        if dataset == "author_profiles":
            selected = columns(AuthorProfile.canonical_author_id, literal("openalex"))
            stmt = select(selected) if count else select(*selected)
            if id_filter:
                stmt = stmt.where(AuthorProfile.canonical_author_id.in_(id_filter))
            stmt = apply_state(stmt, AuthorProfile.canonical_author_id)
            return stmt

        if dataset == "author_work_sync_state":
            selected = columns(AuthorWorkSyncState.canonical_author_id, AuthorWorkSyncState.provider)
            stmt = select(selected) if count else select(*selected)
            if id_filter:
                stmt = stmt.where(AuthorWorkSyncState.canonical_author_id.in_(id_filter))
            if stale_cutoff is not None:
                stmt = stmt.where(
                    or_(
                        AuthorWorkSyncState.last_synced_at.is_(None),
                        AuthorWorkSyncState.last_synced_at < stale_cutoff,
                        AuthorWorkSyncState.status.notin_(("complete", "success")),
                    )
                )
            return stmt

        if dataset == "canonical_author_institutions":
            selected = columns(CanonicalAuthorInstitution.canonical_author_id, CanonicalAuthorInstitution.provider)
            stmt = select(selected) if count else select(*selected)
            if id_filter:
                stmt = stmt.where(CanonicalAuthorInstitution.canonical_author_id.in_(id_filter))
            stmt = apply_state(stmt, CanonicalAuthorInstitution.canonical_author_id)
            return stmt

        if dataset == "work_grant_matches":
            selected = columns(WorkGrantMatch.canonical_work_id, WorkGrantMatch.provider)
            stmt = select(selected) if count else select(*selected)
            if id_filter:
                stmt = stmt.where(WorkGrantMatch.canonical_work_id.in_(id_filter))
            stmt = apply_state(stmt, WorkGrantMatch.canonical_work_id)
            return stmt

        raise ValueError(f"Unsupported dataset: {dataset}")

    async def delete_expired_cache(self) -> int:
        result = await self.session.execute(
            delete(ProviderSearchCache).where(ProviderSearchCache.expires_at <= utc_now())
        )
        return int(result.rowcount or 0)

    async def delete_expired_sessions(self) -> int:
        result = await self.session.execute(
            delete(SearchSession).where(SearchSession.expires_at <= utc_now())
        )
        return int(result.rowcount or 0)
