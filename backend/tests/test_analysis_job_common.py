"""Shared Analyze Authors job helpers (fingerprint + concurrency gate)."""

from __future__ import annotations

import asyncio

import pytest

from app.services.analysis.analysis_job_common import (
    analysis_job_semaphore,
    analysis_request_fingerprint,
    reset_analysis_job_semaphore_for_tests,
)
from app.services.analysis import insights_jobs, publication_stats_jobs
from app.services.analysis.insights_jobs import InsightsJobService, run_insights_job
from app.services.analysis.publication_stats_jobs import (
    PublicationStatsJobService,
    run_publication_stats_job,
)


def test_analysis_request_fingerprint_stable_across_author_order():
    a = {
        "authors": [
            {"canonical_author_id": "b"},
            {"canonical_author_id": "a"},
        ],
        "filters": {"venues": ["Nature"]},
    }
    b = {
        "authors": [
            {"canonical_author_id": "a"},
            {"canonical_author_id": "b"},
        ],
        "filters": {"venues": ["Nature"]},
    }
    assert analysis_request_fingerprint(a, job_kind="insights") == analysis_request_fingerprint(
        b, job_kind="insights"
    )
    assert analysis_request_fingerprint(a, job_kind="insights") != analysis_request_fingerprint(
        a, job_kind="publication_stats"
    )


def test_analysis_request_fingerprint_changes_with_filters():
    base = {"authors": [{"canonical_author_id": "a"}]}
    filtered = {
        "authors": [{"canonical_author_id": "a"}],
        "filters": {"from_year": 2020},
    }
    assert analysis_request_fingerprint(base, job_kind="publication_stats") != (
        analysis_request_fingerprint(filtered, job_kind="publication_stats")
    )


@pytest.mark.asyncio
async def test_stats_and_insights_share_concurrency_semaphore(monkeypatch):
    reset_analysis_job_semaphore_for_tests()
    current = 0
    peak = 0

    class DummySession:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            return False

    async def fake_execute(self, job_id: str) -> None:
        nonlocal current, peak
        current += 1
        peak = max(peak, current)
        await asyncio.sleep(0.05)
        current -= 1

    monkeypatch.setattr(insights_jobs, "SessionLocal", DummySession)
    monkeypatch.setattr(publication_stats_jobs, "SessionLocal", DummySession)
    monkeypatch.setattr(InsightsJobService, "execute", fake_execute)
    monkeypatch.setattr(PublicationStatsJobService, "execute", fake_execute)

    # Shared gate defaults to insights_job_max_concurrency (2).
    await asyncio.gather(
        run_insights_job("i1"),
        run_publication_stats_job("s1"),
        run_insights_job("i2"),
    )
    assert peak <= 2
    # Same semaphore instance for both job kinds.
    assert await analysis_job_semaphore() is await analysis_job_semaphore()
    reset_analysis_job_semaphore_for_tests()
