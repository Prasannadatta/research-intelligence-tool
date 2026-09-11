"""Background Collaboration Insights jobs."""

from __future__ import annotations

import asyncio
import logging
import uuid
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import AnalysisJob
from app.db.models.analysis_job import utc_now
from app.db.session import SessionLocal
from app.services.analysis.analysis_job_common import (
    STATUS_COMPLETED,
    STATUS_FAILED as STATUS_FAILED_JOB,
    STATUS_QUEUED,
    STATUS_RUNNING,
    analysis_job_semaphore,
    analysis_request_fingerprint,
    find_reusable_analysis_job,
    find_reusable_completed_analysis_job,
    reset_analysis_job_semaphore_for_tests,
    run_selected_authors_sync_phase,
    serialize_analysis_job,
)
from app.services.analysis.author_insights import AuthorInsightsService
from app.services.analysis.author_publications import AuthorAnalysisError
from app.services.analysis.author_work_sync import (
    STATUS_COMPLETE,
    STATUS_FAILED,
    AuthorWorkSyncService,
)
from app.services.analysis.publication_enrichment import enrich_selected_authors_publications
from app.services.analysis.sync_job_errors import (
    blocking_sync_problems,
    incomplete_sync_failure,
)

logger = logging.getLogger(__name__)

STAGE_PREPARING = "Preparing"
STAGE_CHECKING_COVERAGE = "Checking publication coverage"
STAGE_SYNCING = "Syncing publications"
STAGE_COLLABORATION = "Calculating collaboration metrics"
STAGE_INSTITUTIONS = "Calculating institutions/citations"
STAGE_JOURNAL_METRICS = "Loading journal metrics"
STAGE_FINALIZING = "Finalizing"
STAGE_COMPLETED = "Completed"
STAGE_FAILED = "Failed"

JOB_KIND = "insights"


def reset_insights_job_semaphore_for_tests() -> None:
    reset_analysis_job_semaphore_for_tests()


# Re-export for API routes / tests that import from this module.
__all__ = [
    "InsightsJobService",
    "JOB_KIND",
    "enqueue_insights_job",
    "reset_insights_job_semaphore_for_tests",
    "run_insights_job",
    "schedule_insights_job",
    "serialize_analysis_job",
]


class InsightsJobService:
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
            logger.warning("insights_job_missing job_id=%s", job_id)
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
            current.progress_percent = max(
                int(current.progress_percent or 0),
                max(0, min(int(percent), 99)),
            )
            if detail is not None:
                current.progress_detail = {**detail, "job_kind": JOB_KIND}
            current.updated_at = utc_now()
            await self.session.commit()

        try:
            await on_progress(STAGE_CHECKING_COVERAGE, 8, {"phase": "checking"})
            payload_sync_mode = (
                "incomplete_only"
                if payload.get("retry_incomplete_only")
                else "needed"
            )
            sync_stats = await run_selected_authors_sync_phase(
                self.session,
                authors,
                on_progress=on_progress,
                sync_mode=payload_sync_mode,
                percent_base=10,
                percent_span=30,
                percent_cap=40,
                default_stage=STAGE_SYNCING,
                checking_stage=STAGE_CHECKING_COVERAGE,
            )
            if sync_stats and all(row.get("network_skipped") for row in sync_stats):
                logger.info(
                    "insights_reused_verified_corpus job_id=%s authors=%s",
                    job_id,
                    len(sync_stats),
                )

            incomplete = incomplete_sync_failure(sync_stats, context="insights")
            if incomplete:
                await self._fail(
                    job_uuid,
                    incomplete["error_message"],
                    detail=incomplete,
                )
                return

            await on_progress(
                "Enriching publication metadata",
                42,
                {"phase": "enriching", "sync_status": STATUS_COMPLETE},
            )
            enrichment = await enrich_selected_authors_publications(
                self.session,
                authors,
            )

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
            if blocking_sync_problems(sync_stats):
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
                # Enrichment overlays never certify completeness.
                "enrichment_applied": True,
                "enrichment_affects_completeness": False,
            }
            result["enrichment"] = enrichment
        except AuthorAnalysisError as exc:
            try:
                await self.session.rollback()
            except Exception:  # noqa: BLE001
                logger.exception("insights_job_rollback_failed job_id=%s", job_id)
            await self._fail(job_uuid, str(exc))
            return
        except Exception:
            logger.exception("insights_job_failed job_id=%s", job_id)
            try:
                await self.session.rollback()
            except Exception:  # noqa: BLE001
                logger.exception("insights_job_rollback_failed job_id=%s", job_id)
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
            "job_kind": JOB_KIND,
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
            "job_kind": JOB_KIND,
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
    """Create an Insights job, reusing in-flight or fresh completed results when safe."""
    fingerprint = analysis_request_fingerprint(payload, job_kind=JOB_KIND)
    existing = await find_reusable_analysis_job(
        session,
        job_kind=JOB_KIND,
        fingerprint=fingerprint,
    )
    if existing is not None:
        return serialize_analysis_job(existing)

    authors = list(payload.get("authors") or [])
    if await AuthorWorkSyncService(session).fresh_verified_sync_stats(authors) is not None:
        completed = await find_reusable_completed_analysis_job(
            session,
            job_kind=JOB_KIND,
            fingerprint=fingerprint,
        )
        if completed is not None:
            return serialize_analysis_job(completed)

    job = await InsightsJobService(session).create_job(payload)
    schedule_insights_job(str(job.id))
    return serialize_analysis_job(job)


def schedule_insights_job(job_id: str) -> None:
    asyncio.create_task(run_insights_job(job_id))


async def run_insights_job(job_id: str) -> None:
    semaphore = await analysis_job_semaphore()
    async with semaphore:
        async with SessionLocal() as session:
            await InsightsJobService(session).execute(job_id)
