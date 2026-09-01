"""Temporary Author Search timing diagnostics. Enable with DIAG_SEARCH_TIMING=1."""

from __future__ import annotations

import logging
import os
import time
from contextlib import contextmanager
from typing import Any

logger = logging.getLogger(__name__)

_ENABLED = os.environ.get("DIAG_SEARCH_TIMING", "").strip().lower() in {
    "1",
    "true",
    "yes",
}

HTTP_CALLS: dict[str, int] = {}
STAGE_MS: dict[str, float] = {}


def enabled() -> bool:
    return _ENABLED


def reset() -> None:
    HTTP_CALLS.clear()
    STAGE_MS.clear()


def record_http(provider: str) -> None:
    if not _ENABLED:
        return
    key = (provider or "other").strip().lower()
    HTTP_CALLS[key] = HTTP_CALLS.get(key, 0) + 1


@contextmanager
def stage(name: str):
    if not _ENABLED:
        yield
        return
    started = time.perf_counter()
    try:
        yield
    finally:
        elapsed_ms = (time.perf_counter() - started) * 1000
        STAGE_MS[name] = STAGE_MS.get(name, 0.0) + elapsed_ms
        logger.info("search_diag stage=%s ms=%.1f", name, elapsed_ms)


def log_summary(*, label: str, extra: dict[str, Any] | None = None) -> None:
    if not _ENABLED:
        return
    payload = {
        "label": label,
        "stage_ms": dict(sorted(STAGE_MS.items())),
        "http_calls": dict(sorted(HTTP_CALLS.items())),
        **(extra or {}),
    }
    logger.info("search_diag summary %s", payload)


def patch_provider_get() -> None:
    if not _ENABLED:
        return
    from app.integrations import rate_limited_http

    original = rate_limited_http.provider_get

    async def wrapped(provider: str, url: str, **kwargs: Any):
        record_http(provider)
        return await original(provider, url, **kwargs)

    rate_limited_http.provider_get = wrapped
