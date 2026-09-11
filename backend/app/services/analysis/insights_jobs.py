"""Background Collaboration Insights jobs."""

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
from app.services.analysis.author_publications import AuthorAnalysisError
from app.services.analysis.author_work_sync import (
    STATUS_COMPLETE,
    STATUS_FAILED,
    AuthorWorkSyncService,
)
from app.services.analysis.sync_job_errors import incomplete_sync_failure as _incomplete_sync_failure

logger = logging.getLogger(__name__)

STATUS_QUEUED = "queued"
STATUS_RUNNING = "running"
STATUS_COMPLETED = "completed"
STATUS_FAILED_JOB = "failed"

STAGE_PREPARING = "Preparing"
STAGE_CHECKING_COVERAGE = "Checking publication coverage"
STAGE_SYNCING = "Syncing publications"
STAGE_COLLABORATION = "Calculating collaboration metrics"
STAGE_INSTITUTIONS = "Calculating institutions/citations"
STAGE_JOURNAL_METRICS = "Loading journal metrics"
STAGE_FINALIZING = "Finalizing"
STAGE_COMPLETED = "Completed"
STAGE_FAILED = "Failed"

_job_semaphore: asyncio.Semaphore | None = None
_job_semaphore_guard = asyncio.Lock()


async def _semaphore() -> asyncio.Semaphore:
    global _job_semaphore
    async with _job_semaphore_guard:
        if _job_semaphore is None:
            _job_semaphore = asyncio.Semaphore(get_settings().insights_job_max_concurrency)
        return _job_semaphore


def reset_insights_job_semaphore_for_tests() -> None:
    global _job_semaphore
    _job_semaphore = None


def serialize_analysis_job(job: AnalysisJob) -> dict[str, Any]:
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
        return STAGE_CHECKING_COVERAGE
    if detail.get("rate_limited"):
        provider = str(detail.get("provider") or "Provider").strip() or "Provider"
        label = {
            "openalex": "OpenAlex",
            "arxiv": "arXiv",
        }.get(provider.lower(), provider[:1].upper() + provider[1:])
        return f"{label} rate limit reached"

    author = str(detail.get("current_author") or "").strip()
    processed = detail.get("publications_processed")
    total = detail.get("publications_total")
    if author and processed is not None and total is not None:
        try:
            return (
                f"Syncing publications for {author} — "
                f"{int(processed):,} / {int(total):,}"
            )
        except (TypeError, ValueError):
            return f"Syncing publications for {author} — {processed} / {total}"
    if author and processed is not None:
        try:
            return f"Syncing publications for {author} — {int(processed):,}"
        except (TypeError, ValueError):
            return f"Syncing publications for {author} — {processed}"
    if author:
        return f"Syncing publications for {author}"
    return STAGE_SYNCING


def _sync_percent(detail: dict[str, Any]) -> int:
    phase = str(detail.get("phase") or "").strip().lower()
    if phase == "checking":
        return 8
    authors_total = max(int(detail.get("authors_total") or 1), 1)
    authors_completed = max(int(detail.get("authors_completed") or 0), 0)
    author_index = int(detail.get("author_index") or max(authors_completed, 1))
    base = 10
    span = 30
    author_fraction = min(max((author_index - 1) / authors_total, 0.0), 1.0)
    processed = detail.get("publications_processed")
    total = detail.get("publications_total")
    page_fraction = 0.0
    try:
        if processed is not None and total and int(total) > 0:
            page_fraction = min(max(int(processed) / int(total), 0.0), 1.0) / authors_total
    except (TypeError, ValueError):
        page_fraction = 0.0
    return min(base + int((author_fraction + page_fraction) * span), 40)


class InsightsJobService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def create_job(self, payload: dict[str, Any]) -> AnalysisJob:
        job = AnalysisJob(
            id=uuid.uuid4(),
            status=STATUS_QUEUED,
            request_payload=payload,
            result=None,
            progress_percent=0,
            progress_stage=STAGE_PREPARING,
            progress_detail=None,
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
            logger.warning("insights_job_missing job_id=%s", job_id)
            return
        if job.status in {STATUS_COMPLETED, STATUS_FAILED_JOB}:
            return

        now = utc_now()
        job.status = STATUS_RUNNING
        job.started_at = job.started_at or now
        job.progress_stage = STAGE_PREPARING
        job.progress_percent = 5
        job.progress_detail = {"phase": "preparing"}
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
                current.progress_detail = detail
            current.updated_at = utc_now()
            await self.session.commit()

        try:
            await on_progress(STAGE_CHECKING_COVERAGE, 8, {"phase": "checking"})

            async def on_sync_progress(detail: dict[str, Any]) -> None:
                await on_progress(
                    _format_sync_stage(detail),
                    _sync_percent(detail),
                    {
                        "author_name": detail.get("current_author"),
                        "author_index": detail.get("author_index"),
                        "author_total": detail.get("authors_total"),
                        "publications_processed": detail.get("publications_processed"),
                        "publications_total": detail.get("publications_total"),
                        "provider": detail.get("provider"),
                        "sync_status": detail.get("sync_status") or detail.get("status"),
                        "phase": detail.get("phase"),
                        "rate_limited": bool(detail.get("rate_limited")),
                    },
                )

            sync_stats = await AuthorWorkSyncService(self.session).synchronize_selected_authors(
                authors,
                on_progress=on_sync_progress,
            )
            incomplete = _incomplete_sync_failure(sync_stats, context="insights")
            if incomplete:
                await self._fail(
                    job_uuid,
                    incomplete["error_message"],
                    detail=incomplete,
                )
                return

            async def on_dashboard_progress(stage: str, percent: int) -> None:
                # Remap legacy "Loading publications" / Preparing into post-sync stages.
                mapped = stage
                mapped_percent = percent
                if stage in {"Preparing", "Loading publications"}:
                    mapped = STAGE_COLLABORATION
                    mapped_percent = max(percent, 45)
                elif stage == "Calculating collaboration metrics":
                    mapped = STAGE_COLLABORATION
                    mapped_percent = max(percent, 45)
                elif stage == "Calculating institutions/citations":
                    mapped = STAGE_INSTITUTIONS
                    mapped_percent = max(percent, 65)
                elif stage == "Loading journal metrics":
                    mapped = STAGE_JOURNAL_METRICS
                    mapped_percent = max(percent, 80)
                elif stage == "Finalizing":
                    mapped = STAGE_FINALIZING
                    mapped_percent = max(percent, 95)
                await on_progress(
                    mapped,
                    mapped_percent,
                    {"phase": "dashboard", "stage": mapped},
                )

            result = await AuthorInsightsService(self.session).build_dashboard(
                authors=authors,
                filters=payload.get("filters"),
                excluded_work_ids=list(payload.get("excluded_work_ids") or []),
                on_progress=on_dashboard_progress,
            )
            from app.services.analysis.sync_job_errors import _blocking_sync_problems

            if _blocking_sync_problems(sync_stats):
                await self._fail(
                    job_uuid,
                    "Publication coverage is incomplete for the selected authors, "
                    "so Collaboration Insights cannot be marked complete.",
                    detail={"sync_status": STATUS_FAILED, "rate_limited": False},
                )
                return
            result["coverage"] = {
                "verified": True,
                "corpus_complete": True,
                "source": "stored_complete_corpus",
            }
        except AuthorAnalysisError as exc:
            await self._fail(job_uuid, str(exc))
            return
        except Exception:
            logger.exception("insights_job_failed job_id=%s", job_id)
            await self._fail(job_uuid, "Collaboration Insights job failed.")
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
            "sync_status": STATUS_COMPLETE,
            "corpus_complete": True,
            "authors_synced": len(sync_stats),
        }
        current.error_message = None
        current.completed_at = utc_now()
        current.updated_at = current.completed_at
        await self.session.commit()

    async def _fail(
        self,
        job_id: uuid.UUID,
        message: str,
        *,
        detail: dict[str, Any] | None = None,
    ) -> None:
        job = await self.get_job(job_id)
        if job is None:
            return
        job.status = STATUS_FAILED_JOB
        job.error_message = message
        job.progress_stage = STAGE_FAILED
        extra = detail or {}
        job.progress_detail = {
            "phase": "failed",
            "sync_status": extra.get("sync_status") or STATUS_FAILED,
            "error_message": message,
            "rate_limited": bool(extra.get("rate_limited")),
            "provider": extra.get("provider"),
            "providers": list(extra.get("providers") or []),
            "corpus_complete": False,
        }
        job.completed_at = utc_now()
        job.updated_at = job.completed_at
        await self.session.commit()


async def enqueue_insights_job(
    session: AsyncSession,
    payload: dict[str, Any],
) -> dict[str, Any]:
    job = await InsightsJobService(session).create_job(payload)
    schedule_insights_job(str(job.id))
    return serialize_analysis_job(job)


def schedule_insights_job(job_id: str) -> None:
    asyncio.create_task(run_insights_job(job_id))


async def run_insights_job(job_id: str) -> None:
    semaphore = await _semaphore()
    async with semaphore:
        async with SessionLocal() as session:
            await InsightsJobService(session).execute(job_id)
