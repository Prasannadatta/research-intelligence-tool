#!/usr/bin/env python3
"""Temporary Author Search timing reproduction. Usage: DIAG_SEARCH_TIMING=1 python scripts/diagnose_author_search_timing.py"""

from __future__ import annotations

import asyncio
import logging
import os
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

os.environ.setdefault("DIAG_SEARCH_TIMING", "1")

logging.basicConfig(level=logging.INFO, format="%(message)s")

from app.core.config import get_settings
from app.services.search.diag_timing import HTTP_CALLS, STAGE_MS, log_summary, reset
from app.services.search.search_service import run_search

LIN_LIN = "Lin Lin"
LIN_ORCID = "0000-0001-6860-9566"

SCENARIOS = [
    ("all", LIN_LIN),
    ("openalex", LIN_LIN),
    ("orcid", LIN_LIN),
    ("orcid", LIN_ORCID),
    ("all", LIN_ORCID),
    ("openalex", LIN_ORCID),
]


async def run_case(source: str, query: str) -> dict:
    reset()
    get_settings.cache_clear()
    started = time.perf_counter()
    payload = await run_search(
        query=query,
        entity_type="authors",
        source=source,
        limit=20,
    )
    total_ms = (time.perf_counter() - started) * 1000
    summary = {
        "source": source,
        "query": query,
        "total_ms": round(total_ms, 1),
        "result_count": len(payload.get("results") or []),
        "stage_ms": dict(sorted(STAGE_MS.items())),
        "http_calls": dict(sorted(HTTP_CALLS.items())),
    }
    log_summary(label=f"{source}:{query}", extra=summary)
    return summary


async def main() -> None:
    if not get_settings().openalex_api_key:
        print("WARNING: OPENALEX_API_KEY not set; OpenAlex calls may fail.")
    if not get_settings().orcid_configured:
        print("WARNING: ORCID_ENABLED is false; ORCID paths will be empty.")

    rows = []
    for source, query in SCENARIOS:
        print(f"\n=== source={source} query={query!r} ===")
        try:
            rows.append(await run_case(source, query))
        except Exception as exc:
            print(f"FAILED: {exc}")
            rows.append({"source": source, "query": query, "error": str(exc)})

    print("\n\n=== SUMMARY TABLE ===")
    for row in rows:
        if row.get("error"):
            print(f"{row['source']:8} {row['query']:24} ERROR {row['error']}")
            continue
        http = ", ".join(f"{k}={v}" for k, v in row.get("http_calls", {}).items()) or "-"
        slowest = "-"
        if row.get("stage_ms"):
            name, ms = max(row["stage_ms"].items(), key=lambda item: item[1])
            slowest = f"{name}={ms:.0f}ms"
        print(
            f"{row['source']:8} {row['query']:24} "
            f"total={row['total_ms']:7.0f}ms results={row['result_count']:2} "
            f"http[{http}] slowest[{slowest}]"
        )


if __name__ == "__main__":
    asyncio.run(main())
