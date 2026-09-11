"""Shared helpers for Analyze Authors background jobs (stats + Insights)."""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.db.models import AnalysisJob
from app.services.analysis.publication_filters import normalize_filters

logger = logging.getLogger(__name__)

STATUS_QUEUED = "queued"
STATUS_RUNNING = "running"
STATUS_COMPLETED = "completed"
STATUS_FAILED = "failed"

# One process-wide gate for sync-heavy Analyze jobs (stats + Insights).
_analysis_job_semaphore: asyncio.Semaphore | None = None
_analysis_job_semaphore_guard = asyncio.Lock()


async def analysis_job_semaphore() -> asyncio.Semaphore:
    """Shared concurrency limit for publication-stats and Insights jobs."""
    global _analysis_job_semaphore
    async with _analysis_job_semaphore_guard:
        if _analysis_job_semaphore is None:
            _analysis_job_semaphore = asyncio.Semaphore(
                get_settings().insights_job_max_concurrency
            )
        return _analysis_job_semaphore


def reset_analysis_job_semaphore_for_tests() -> None:
    global _analysis_job_semaphore
    _analysis_job_semaphore = None


def canonical_author_ids(payload: dict[str, Any]) -> list[str]:
    authors = payload.get("authors") or []
    return sorted(
        {
            str(row.get("canonical_author_id") or "").strip()
            for row in authors
            if isinstance(row, dict) and row.get("canonical_author_id")
        }
    )


def analysis_request_fingerprint(
    payload: dict[str, Any],
    *,
    job_kind: str,
) -> str:
    """Stable fingerprint for in-flight job reuse (authors + filters + exclusions)."""
    ids = canonical_author_ids(payload)
    filters = normalize_filters(payload.get("filters"))
    filters_key = json.dumps(filters, sort_keys=True, separators=(",", ":"), default=str)
    excluded = sorted(
        {
            str(value).strip()
            for value in (payload.get("excluded_work_ids") or [])
            if str(value).strip()
        }
    )
    return f"{job_kind}|{','.join(ids)}|{filters_key}|{','.join(excluded)}"


async def find_reusable_analysis_job(
    session: AsyncSession,
    *,
    job_kind: str,
    fingerprint: str,
    limit: int = 40,
) -> AnalysisJob | None:
    """Reuse an in-flight job with the same kind + fingerprint, if any."""
    rows = (
        await session.execute(
            select(AnalysisJob)
            .where(AnalysisJob.status.in_([STATUS_QUEUED, STATUS_RUNNING]))
            .order_by(AnalysisJob.created_at.desc())
            .limit(limit)
        )
    ).scalars().all()
    for existing in rows:
        request = existing.request_payload if isinstance(existing.request_payload, dict) else {}
        if request.get("job_kind") != job_kind:
            continue
        if analysis_request_fingerprint(request, job_kind=job_kind) == fingerprint:
            logger.info(
                "analysis_job_reused job_kind=%s job_id=%s fingerprint=%s",
                job_kind,
                existing.id,
                fingerprint,
            )
            return existing
    return None


def completed_job_result_is_reusable(job: AnalysisJob) -> bool:
    """True when a completed job result was built from a verified complete corpus."""
    result = job.result if isinstance(job.result, dict) else None
    if not result:
        return False
    if result.get("corpus_complete") is True:
        return True
    coverage = result.get("coverage")
    if not isinstance(coverage, dict):
        return False
    if coverage.get("corpus_complete") is True:
        return True
    return (
        coverage.get("verified") is True
        and coverage.get("source") == "stored_complete_corpus"
    )


async def find_reusable_completed_analysis_job(
    session: AsyncSession,
    *,
    job_kind: str,
    fingerprint: str,
    limit: int = 40,
) -> AnalysisJob | None:
    """Reuse a completed job with the same fingerprint (caller must verify freshness)."""
    rows = (
        await session.execute(
            select(AnalysisJob)
            .where(AnalysisJob.status == STATUS_COMPLETED)
            .order_by(AnalysisJob.completed_at.desc(), AnalysisJob.created_at.desc())
            .limit(limit)
        )
    ).scalars().all()
    for existing in rows:
        request = existing.request_payload if isinstance(existing.request_payload, dict) else {}
        if request.get("job_kind") != job_kind:
            continue
        if analysis_request_fingerprint(request, job_kind=job_kind) != fingerprint:
            continue
        if not completed_job_result_is_reusable(existing):
            continue
        logger.info(
            "analysis_job_reused_completed job_kind=%s job_id=%s fingerprint=%s",
            job_kind,
            existing.id,
            fingerprint,
        )
        return existing
    return None


def serialize_analysis_job(job: AnalysisJob) -> dict[str, Any]:
    """Shared API serialization for publication-stats and Insights jobs."""
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


def format_sync_progress_stage(
    detail: dict[str, Any],
    *,
    default_stage: str = "Syncing publications",
    checking_stage: str = "Checking publication coverage",
) -> str:
    phase = str(detail.get("phase") or "").strip().lower()
    if phase == "checking":
        return checking_stage
    if detail.get("rate_limited"):
        provider = str(detail.get("provider") or "Provider").strip() or "Provider"
        label = {
            "openalex": "OpenAlex",
            "arxiv": "arXiv",
        }.get(provider.lower(), provider[:1].upper() + provider[1:])
        return f"{label} rate limit reached"

    authors_ready = detail.get("authors_ready")
    authors_total = detail.get("authors_total")
    ready_label = None
    try:
        if authors_ready is not None and authors_total is not None:
            ready_label = f"{int(authors_ready)} of {int(authors_total)} authors ready"
    except (TypeError, ValueError):
        ready_label = None

    author = str(detail.get("current_author") or "").strip()
    processed = detail.get("publications_processed")
    total = detail.get("publications_total")
    if ready_label and author and processed is not None and total is not None:
        try:
            return (
                f"{ready_label} — syncing {author} "
                f"({int(processed):,} / {int(total):,})"
            )
        except (TypeError, ValueError):
            return f"{ready_label} — syncing {author} ({processed} / {total})"
    if ready_label and author:
        return f"{ready_label} — syncing {author}"
    if ready_label:
        return ready_label
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
    return default_stage


def sync_progress_percent(
    detail: dict[str, Any],
    *,
    base: int = 10,
    span: int = 55,
    cap: int = 70,
) -> int:
    """Percent from authors_ready / authors_total (monotonic-friendly).

    Prefer ready-count so progress never jumps backwards when switching authors
    or when a new author's publication counter resets to 0.
    """
    phase = str(detail.get("phase") or "").strip().lower()
    if phase == "checking":
        return 8
    authors_total = max(int(detail.get("authors_total") or 1), 1)
    try:
        authors_ready = int(detail.get("authors_ready") or 0)
    except (TypeError, ValueError):
        authors_ready = 0
    authors_ready = min(max(authors_ready, 0), authors_total)

    # Optional fractional progress for the author currently in flight.
    in_progress = 0.0
    if authors_ready < authors_total:
        processed = detail.get("publications_processed")
        total = detail.get("publications_total")
        try:
            if processed is not None and total and int(total) > 0:
                in_progress = min(max(int(processed) / int(total), 0.0), 0.99)
        except (TypeError, ValueError):
            in_progress = 0.0

    fraction = min((authors_ready + in_progress) / authors_total, 1.0)
    return min(base + int(fraction * span), cap)


def sync_progress_detail(detail: dict[str, Any]) -> dict[str, Any]:
    """Normalize sync callback detail for job progress_detail persistence."""
    return {
        "phase": detail.get("phase") or "syncing",
        "author_name": detail.get("current_author"),
        "author_index": detail.get("author_index"),
        "author_total": detail.get("authors_total"),
        "authors_ready": detail.get("authors_ready"),
        "authors_total": detail.get("authors_total"),
        "publications_processed": detail.get("publications_processed"),
        "publications_total": detail.get("publications_total"),
        "provider": detail.get("provider"),
        "sync_status": detail.get("sync_status") or detail.get("status"),
        "rate_limited": bool(detail.get("rate_limited")),
        "network_skipped": bool(detail.get("network_skipped")),
    }


async def run_selected_authors_sync_phase(
    session: AsyncSession,
    authors: list[dict[str, Any]],
    *,
    on_progress: Any,
    sync_mode: str = "needed",
    percent_base: int = 10,
    percent_span: int = 55,
    percent_cap: int = 70,
    default_stage: str = "Syncing publications",
    checking_stage: str = "Checking publication coverage",
) -> list[dict[str, Any]]:
    """Shared stats/Insights sync phase: reuse fresh corpus or sync only what is needed."""
    from app.services.analysis.author_work_sync import AuthorWorkSyncService

    sync_service = AuthorWorkSyncService(session)
    # Removing authors / filter-only remounts: zero provider work when all remaining fresh.
    sync_stats = await sync_service.fresh_verified_sync_stats(authors)
    if sync_stats is not None:
        return sync_stats

    high_water = 8

    async def on_sync_progress(detail: dict[str, Any]) -> None:
        nonlocal high_water
        percent = sync_progress_percent(
            detail,
            base=percent_base,
            span=percent_span,
            cap=percent_cap,
        )
        high_water = max(high_water, percent)
        await on_progress(
            format_sync_progress_stage(
                detail,
                default_stage=default_stage,
                checking_stage=checking_stage,
            ),
            high_water,
            sync_progress_detail(detail),
        )

    return await sync_service.synchronize_selected_authors(
        authors,
        on_progress=on_sync_progress,
        sync_mode=sync_mode,
    )
