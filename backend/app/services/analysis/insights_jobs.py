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

logger = logging.getLogger(__name__)

STATUS_QUEUED = "queued"
STATUS_RUNNING = "running"
STATUS_COMPLETED = "completed"
STATUS_FAILED = "failed"

STAGE_PREPARING = "Preparing"
STAGE_LOADING_PUBLICATIONS = "Loading publications"
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
        "error_message": job.error_message,
        "created_at": job.created_at,
        "updated_at": job.updated_at,
        "started_at": job.started_at,
        "completed_at": job.completed_at,
    }


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
        if job.status in {STATUS_COMPLETED, STATUS_FAILED}:
            return

        now = utc_now()
        job.status = STATUS_RUNNING
        job.started_at = job.started_at or now
        job.progress_stage = STAGE_PREPARING
        job.progress_percent = 5
        job.updated_at = now
        await self.session.commit()

        payload = job.request_payload if isinstance(job.request_payload, dict) else {}

        async def on_progress(stage: str, percent: int) -> None:
            current = await self.get_job(job_uuid)
            if current is None or current.status != STATUS_RUNNING:
                return
            current.progress_stage = stage
            current.progress_percent = max(0, min(int(percent), 99))
            current.updated_at = utc_now()
            await self.session.commit()

        try:
            result = await AuthorInsightsService(self.session).build_dashboard(
                authors=list(payload.get("authors") or []),
                filters=payload.get("filters"),
                excluded_work_ids=list(payload.get("excluded_work_ids") or []),
                on_progress=on_progress,
            )
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
        current.error_message = None
        current.completed_at = utc_now()
        current.updated_at = current.completed_at
        await self.session.commit()

    async def _fail(self, job_id: uuid.UUID, message: str) -> None:
        job = await self.get_job(job_id)
        if job is None:
            return
        job.status = STATUS_FAILED
        job.error_message = message
        job.progress_stage = STAGE_FAILED
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
