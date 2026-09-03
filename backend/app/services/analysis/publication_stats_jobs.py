"""Background Analyze Authors full-corpus timeline/facet jobs."""

from __future__ import annotations

import asyncio
import logging
import uuid
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.db.models import AnalysisJob
from app.db.models.analysis_job import utc_now
from app.db.session import SessionLocal
from app.services.analysis.author_insights import AuthorInsightsService
from app.services.analysis.author_publications import (
    AuthorAnalysisError,
    build_publication_timeline,
)
from app.services.analysis.author_work_sync import (
    STATUS_COMPLETE,
    STATUS_FAILED,
    AuthorWorkSyncService,
)
from app.services.analysis.publication_filters import (
    apply_publication_filters,
    build_dependent_publication_facets,
    normalize_filters,
)

logger = logging.getLogger(__name__)

STATUS_QUEUED = "queued"
STATUS_RUNNING = "running"
STATUS_COMPLETED = "completed"
STATUS_FAILED_JOB = "failed"

STAGE_PREPARING = "Preparing"
STAGE_CHECKING = "Checking publication coverage"
STAGE_SYNCING = "Syncing publications"
STAGE_BUILDING = "Building complete publication statistics"
STAGE_COMPLETED = "Completed"
STAGE_FAILED = "Failed"

JOB_KIND = "publication_stats"

_job_semaphore: asyncio.Semaphore | None = None
_job_semaphore_guard = asyncio.Lock()


async def _semaphore() -> asyncio.Semaphore:
    global _job_semaphore
    async with _job_semaphore_guard:
        if _job_semaphore is None:
            _job_semaphore = asyncio.Semaphore(get_settings().insights_job_max_concurrency)
        return _job_semaphore


def reset_publication_stats_job_semaphore_for_tests() -> None:
    global _job_semaphore
    _job_semaphore = None


def serialize_publication_stats_job(job: AnalysisJob) -> dict[str, Any]:
    return {
        "job_id": str(job.id),
        "status": job.status,
        "request_payload": job.request_payload,
        "result": job.result,
        "progress_percent": int(job.progress_percent or 0),
        "progress_stage": job.progress_stage,
        "progress_detail": job.progress_detail if isinstance(job.progress_detail, dict) else None,
        "error_message": job.error_message,
        "created_at": job.created_at,
        "updated_at": job.updated_at,
        "started_at": job.started_at,
        "completed_at": job.completed_at,
    }


def _format_sync_stage(detail: dict[str, Any]) -> str:
    phase = str(detail.get("phase") or "").strip().lower()
    if phase == "checking":
        return STAGE_CHECKING
    author = str(detail.get("current_author") or "").strip()
    processed = detail.get("publications_processed")
    total = detail.get("publications_total")
    if author and processed is not None and total is not None:
        try:
            return (
                f"Building complete publication statistics — "
                f"{int(processed):,} / {int(total):,}"
            )
        except (TypeError, ValueError):
            return f"Building complete publication statistics — {processed} / {total}"
    if processed is not None and total is not None:
        try:
            return (
                f"Building complete publication statistics — "
                f"{int(processed):,} / {int(total):,}"
            )
        except (TypeError, ValueError):
            return f"Building complete publication statistics — {processed} / {total}"
    if author:
        return f"Building complete publication statistics for {author}"
    return STAGE_BUILDING


def _sync_percent(detail: dict[str, Any]) -> int:
    phase = str(detail.get("phase") or "").strip().lower()
    if phase == "checking":
        return 8
    authors_total = max(int(detail.get("authors_total") or 1), 1)
    author_index = int(detail.get("author_index") or 1)
    base = 10
    span = 55
    author_fraction = min(max((author_index - 1) / authors_total, 0.0), 1.0)
    processed = detail.get("publications_processed")
    total = detail.get("publications_total")
    page_fraction = 0.0
    try:
        if processed is not None and total and int(total) > 0:
            page_fraction = min(max(int(processed) / int(total), 0.0), 1.0) / authors_total
    except (TypeError, ValueError):
        page_fraction = 0.0
    return min(base + int((author_fraction + page_fraction) * span), 70)


def _incomplete_sync_message(stats: list[dict[str, Any]]) -> str | None:
    problems = [
        row
        for row in stats
        if str(row.get("status") or "").lower()
        not in {STATUS_COMPLETE, "fresh", "success"}
    ]
    if not problems:
        return None
    parts: list[str] = []
    for row in problems:
        name = row.get("display_name") or row.get("canonical_author_id") or "Selected author"
        provider = row.get("provider") or "provider"
        status = row.get("status") or STATUS_FAILED
        detail = row.get("error_message")
        if detail:
            parts.append(f"{name} ({provider}): {status} — {detail}")
        else:
            parts.append(f"{name} ({provider}): {status}")
    joined = "; ".join(parts[:3])
    if len(parts) > 3:
        joined = f"{joined}; +{len(parts) - 3} more"
    return (
        "Complete publication statistics are unavailable because coverage sync "
        f"did not finish. {joined}"
    )


async def build_publication_corpus_stats(
    session: AsyncSession,
    *,
    authors: list[dict[str, Any]],
    filters: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build timeline + facets from stored complete corpus for Analyze Authors."""
    insights = AuthorInsightsService(session)
    selected = await insights._resolve_selected_authors(authors)
    selected_ids = [author.canonical_author_id for author in selected]
    mode = "single_author" if len(selected_ids) == 1 else "common_publications"

    membership = await insights._load_work_membership(selected_ids)
    selected_set = set(selected_ids)
    if mode == "single_author":
        matching_ids = set(membership.keys())
    else:
        matching_ids = {
            work_id
            for work_id, author_ids in membership.items()
            if selected_set.issubset(author_ids)
        }

    stored = await insights._load_stored_work_insights(matching_ids)
    filter_items = [work.as_filter_item() for work in stored.values()]

    normalized = normalize_filters(filters)
    facets = build_dependent_publication_facets(filter_items, normalized)
    filtered = apply_publication_filters(filter_items, normalized)
    timeline = build_publication_timeline(filtered)
    return {
        "mode": mode,
        "authors": [
            {
                "canonical_author_id": author.canonical_author_id,
                "display_name": author.display_name,
            }
            for author in selected
        ],
        "timeline": timeline,
        "facets": facets,
        "total_matching_publications": len(filtered),
        "total_corpus_publications": len(filter_items),
        "corpus_complete": True,
    }


class PublicationStatsJobService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def create_job(self, payload: dict[str, Any]) -> AnalysisJob:
        job = AnalysisJob(
            id=uuid.uuid4(),
            status=STATUS_QUEUED,
            request_payload={**payload, "job_kind": JOB_KIND},
            result=None,
            progress_percent=0,
            progress_stage=STAGE_PREPARING,
            progress_detail={"phase": "preparing", "job_kind": JOB_KIND},
            error_message=None,
        )
        self.session.add(job)
        await self.session.commit()
        await self.session.refresh(job)
        return job

    async def get_job(self, job_id: uuid.UUID) -> AnalysisJob | None:
        return await self.session.get(AnalysisJob, job_id)

    async def execute(self, job_id: str) -> None:
        job_uuid = uuid.UUID(str(job_id))
        job = await self.get_job(job_uuid)
        if job is None:
            logger.warning("publication_stats_job_missing job_id=%s", job_id)
            return
        if job.status in {STATUS_COMPLETED, STATUS_FAILED_JOB}:
            return

        now = utc_now()
        job.status = STATUS_RUNNING
        job.started_at = job.started_at or now
        job.progress_stage = STAGE_PREPARING
        job.progress_percent = 5
        job.progress_detail = {"phase": "preparing", "job_kind": JOB_KIND}
        job.updated_at = now
        await self.session.commit()

        payload = job.request_payload if isinstance(job.request_payload, dict) else {}
        authors = list(payload.get("authors") or [])

        async def on_progress(
            stage: str,
            percent: int,
            detail: dict[str, Any] | None = None,
        ) -> None:
            current = await self.get_job(job_uuid)
            if current is None or current.status != STATUS_RUNNING:
                return
            current.progress_stage = stage
            current.progress_percent = max(0, min(int(percent), 99))
            if detail is not None:
                current.progress_detail = {**detail, "job_kind": JOB_KIND}
            current.updated_at = utc_now()
            await self.session.commit()

        try:
            await on_progress(STAGE_CHECKING, 8, {"phase": "checking"})

            async def on_sync_progress(detail: dict[str, Any]) -> None:
                await on_progress(
                    _format_sync_stage(detail),
                    _sync_percent(detail),
                    {
                        "phase": detail.get("phase") or "syncing",
                        "author_name": detail.get("current_author"),
                        "author_index": detail.get("author_index"),
                        "author_total": detail.get("authors_total"),
                        "publications_processed": detail.get("publications_processed"),
                        "publications_total": detail.get("publications_total"),
                        "provider": detail.get("provider"),
                        "sync_status": detail.get("sync_status") or detail.get("status"),
                    },
                )

            sync_stats = await AuthorWorkSyncService(self.session).synchronize_selected_authors(
                authors,
                on_progress=on_sync_progress,
            )
            incomplete = _incomplete_sync_message(sync_stats)
            if incomplete:
                await self._fail(job_uuid, incomplete)
                return

            await on_progress(
                STAGE_BUILDING,
                80,
                {"phase": "building", "sync_status": STATUS_COMPLETE},
            )
            result = await build_publication_corpus_stats(
                self.session,
                authors=authors,
                filters=payload.get("filters"),
            )
        except AuthorAnalysisError as exc:
            await self._fail(job_uuid, str(exc))
            return
        except Exception:
            logger.exception("publication_stats_job_failed job_id=%s", job_id)
            await self._fail(
                job_uuid,
                "Complete publication statistics job failed.",
            )
            return

        current = await self.get_job(job_uuid)
        if current is None:
            return
        current.status = STATUS_COMPLETED
        current.result = result
        current.progress_stage = STAGE_COMPLETED
        current.progress_percent = 100
        current.progress_detail = {
            "phase": "completed",
            "job_kind": JOB_KIND,
            "sync_status": STATUS_COMPLETE,
            "total_matching_publications": result.get("total_matching_publications"),
        }
        current.error_message = None
        current.completed_at = utc_now()
        current.updated_at = current.completed_at
        await self.session.commit()

    async def _fail(self, job_id: uuid.UUID, message: str) -> None:
        job = await self.get_job(job_id)
        if job is None:
            return
        job.status = STATUS_FAILED_JOB
        job.error_message = message
        job.progress_stage = STAGE_FAILED
        job.progress_detail = {
            "phase": "failed",
            "job_kind": JOB_KIND,
            "sync_status": STATUS_FAILED,
            "error_message": message,
        }
        job.completed_at = utc_now()
        job.updated_at = job.completed_at
        await self.session.commit()


async def enqueue_publication_stats_job(
    session: AsyncSession,
    payload: dict[str, Any],
) -> dict[str, Any]:
    job = await PublicationStatsJobService(session).create_job(payload)
    schedule_publication_stats_job(str(job.id))
    return serialize_publication_stats_job(job)


def schedule_publication_stats_job(job_id: str) -> None:
    asyncio.create_task(run_publication_stats_job(job_id))


async def run_publication_stats_job(job_id: str) -> None:
    semaphore = await _semaphore()
    async with semaphore:
        async with SessionLocal() as session:
            await PublicationStatsJobService(session).execute(job_id)
