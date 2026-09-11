"""Background Analyze Authors full-corpus timeline/facet jobs."""

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
from app.services.analysis.author_publications import (
    AuthorAnalysisError,
    build_publication_timeline,
)
from app.services.analysis.author_work_sync import (
    STATUS_COMPLETE,
    STATUS_FAILED,
    AuthorWorkSyncService,
)
from app.services.analysis.publication_corpus import load_stored_publication_filter_items
from app.services.analysis.publication_enrichment import enrich_selected_authors_publications
from app.services.analysis.publication_filters import (
    apply_publication_filters,
    build_dependent_publication_facets,
    normalize_filters,
)
from app.services.analysis.sync_job_errors import (
    blocking_sync_problems,
    incomplete_sync_failure,
)

logger = logging.getLogger(__name__)

STAGE_PREPARING = "Preparing"
STAGE_CHECKING = "Checking publication coverage"
STAGE_SYNCING = "Syncing publications"
STAGE_BUILDING = "Building complete publication statistics"
STAGE_COMPLETED = "Completed"
STAGE_FAILED = "Failed"

JOB_KIND = "publication_stats"


def reset_publication_stats_job_semaphore_for_tests() -> None:
    reset_analysis_job_semaphore_for_tests()


def serialize_publication_stats_job(job: AnalysisJob) -> dict[str, Any]:
    return serialize_analysis_job(job)


async def build_publication_corpus_stats(
    session: AsyncSession,
    *,
    authors: list[dict[str, Any]],
    filters: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build timeline + facets from stored complete corpus for Analyze Authors."""
    loaded = await load_stored_publication_filter_items(session, authors)
    filter_items = loaded["filter_items"]

    normalized = normalize_filters(filters)
    facets = build_dependent_publication_facets(filter_items, normalized)
    filtered = apply_publication_filters(filter_items, normalized)
    timeline = build_publication_timeline(filtered)
    return {
        "mode": loaded["mode"],
        "authors": loaded["authors"],
        "timeline": timeline,
        "facets": facets,
        "total_matching_publications": len(filtered),
        "total_corpus_publications": len(filter_items),
        # Caller must explicitly set True only after verified sync completeness.
        "corpus_complete": False,
        "coverage": {
            "verified": False,
            "source": "stored_corpus",
        },
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
            # Never let percent move backwards within a running job.
            current.progress_percent = max(
                int(current.progress_percent or 0),
                max(0, min(int(percent), 99)),
            )
            if detail is not None:
                current.progress_detail = {**detail, "job_kind": JOB_KIND}
            current.updated_at = utc_now()
            await self.session.commit()

        try:
            await on_progress(STAGE_CHECKING, 8, {"phase": "checking"})
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
                percent_span=55,
                percent_cap=70,
                default_stage=STAGE_SYNCING,
                checking_stage=STAGE_CHECKING,
            )
            if sync_stats and all(row.get("network_skipped") for row in sync_stats):
                logger.info(
                    "publication_stats_reused_verified_corpus job_id=%s authors=%s",
                    job_id,
                    len(sync_stats),
                )

            incomplete = incomplete_sync_failure(sync_stats, context="publication_stats")
            if incomplete:
                await self._fail(
                    job_uuid,
                    incomplete["error_message"],
                    detail=incomplete,
                )
                return

            await on_progress(
                "Enriching publication metadata",
                74,
                {"phase": "enriching", "sync_status": STATUS_COMPLETE},
            )
            enrichment = await enrich_selected_authors_publications(
                self.session,
                authors,
            )

            await on_progress(
                STAGE_BUILDING,
                80,
                {
                    "phase": "building",
                    "sync_status": STATUS_COMPLETE,
                    "enrichment": enrichment,
                },
            )
            result = await build_publication_corpus_stats(
                self.session,
                authors=authors,
                filters=payload.get("filters"),
            )
            # Hard gate: never label complete unless every blocking sync stat is verified.
            if blocking_sync_problems(sync_stats):
                await self._fail(
                    job_uuid,
                    "Complete publication statistics are unavailable because coverage "
                    "was not verified complete.",
                    detail={"sync_status": STATUS_FAILED, "rate_limited": False},
                )
                return
            result["corpus_complete"] = True
            result["coverage"] = {
                "verified": True,
                "source": "stored_complete_corpus",
                "corpus_complete": True,
                "enrichment_applied": True,
                "enrichment_affects_completeness": False,
            }
            result["enrichment"] = enrichment
            result["sync_stats"] = [
                {
                    "canonical_author_id": row.get("canonical_author_id"),
                    "provider": row.get("provider"),
                    "stored_work_count": row.get("stored_work_count_after"),
                    "provider_work_count": row.get("provider_work_count"),
                    "status": row.get("status"),
                    "coverage_verified": bool(row.get("coverage_verified")),
                }
                for row in sync_stats
            ]
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
            "corpus_complete": True,
            "total_matching_publications": result.get("total_matching_publications"),
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


async def enqueue_publication_stats_job(
    session: AsyncSession,
    payload: dict[str, Any],
) -> dict[str, Any]:
    """Create a stats job, reusing in-flight or fresh completed results when safe."""
    fingerprint = analysis_request_fingerprint(payload, job_kind=JOB_KIND)
    existing = await find_reusable_analysis_job(
        session,
        job_kind=JOB_KIND,
        fingerprint=fingerprint,
    )
    if existing is not None:
        return serialize_publication_stats_job(existing)

    authors = list(payload.get("authors") or [])
    # Same authors/filters + still-fresh verified corpus: reuse prior completed result.
    if await AuthorWorkSyncService(session).fresh_verified_sync_stats(authors) is not None:
        completed = await find_reusable_completed_analysis_job(
            session,
            job_kind=JOB_KIND,
            fingerprint=fingerprint,
        )
        if completed is not None:
            return serialize_publication_stats_job(completed)

    job = await PublicationStatsJobService(session).create_job(payload)
    schedule_publication_stats_job(str(job.id))
    return serialize_publication_stats_job(job)


def schedule_publication_stats_job(job_id: str) -> None:
    asyncio.create_task(run_publication_stats_job(job_id))


async def run_publication_stats_job(job_id: str) -> None:
    semaphore = await analysis_job_semaphore()
    async with semaphore:
        async with SessionLocal() as session:
            await PublicationStatsJobService(session).execute(job_id)
