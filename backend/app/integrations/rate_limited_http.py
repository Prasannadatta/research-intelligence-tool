"""Reusable rate-limited HTTP client helpers for external providers."""

from __future__ import annotations

import asyncio
import random
import time
from email.utils import parsedate_to_datetime
from typing import Any

import httpx

from app.core.config import get_settings


class ProviderRequestError(Exception):
    """Raised after retryable provider requests are exhausted."""


class _ProviderLimiter:
    def __init__(self, *, min_interval_seconds: float, concurrency: int) -> None:
        self.min_interval_seconds = max(float(min_interval_seconds or 0), 0)
        self.semaphore = asyncio.Semaphore(max(int(concurrency or 1), 1))
        self.lock = asyncio.Lock()
        self.last_request_at = 0.0

    async def wait_turn(self) -> None:
        async with self.lock:
            now = time.monotonic()
            wait_for = self.min_interval_seconds - (now - self.last_request_at)
            if wait_for > 0:
                await asyncio.sleep(wait_for)
            self.last_request_at = time.monotonic()


_limiters: dict[str, _ProviderLimiter] = {}
_limiters_lock = asyncio.Lock()


def _provider_settings(provider: str) -> tuple[float, int]:
    settings = get_settings()
    normalized = str(provider or "").strip().lower()
    if normalized == "arxiv":
        return (
            settings.arxiv_rate_limit_min_interval_seconds,
            settings.arxiv_rate_limit_concurrency,
        )
    if normalized == "openalex":
        return (
            settings.openalex_rate_limit_min_interval_seconds,
            settings.openalex_rate_limit_concurrency,
        )
    if normalized == "elsevier":
        return (
            settings.elsevier_rate_limit_min_interval_seconds,
            settings.elsevier_rate_limit_concurrency,
        )
    if normalized == "orcid":
        return (
            settings.orcid_rate_limit_min_interval_seconds,
            settings.orcid_rate_limit_concurrency,
        )
    return (1.0, 1)


async def _limiter_for(provider: str) -> _ProviderLimiter:
    normalized = str(provider or "default").strip().lower()
    async with _limiters_lock:
        limiter = _limiters.get(normalized)
        if limiter is None:
            min_interval, concurrency = _provider_settings(normalized)
            limiter = _ProviderLimiter(
                min_interval_seconds=min_interval,
                concurrency=concurrency,
            )
            _limiters[normalized] = limiter
        return limiter


def _retry_after_seconds(value: str | None) -> float | None:
    if not value:
        return None
    text = value.strip()
    try:
        return max(float(text), 0.0)
    except ValueError:
        pass
    try:
        parsed = parsedate_to_datetime(text)
    except (TypeError, ValueError):
        return None
    delay = parsed.timestamp() - time.time()
    return max(delay, 0.0)


def _retryable_response(response: httpx.Response) -> bool:
    return response.status_code == 429 or 500 <= response.status_code < 600


def _retryable_exception(exc: Exception) -> bool:
    return isinstance(
        exc,
        (
            httpx.ConnectError,
            httpx.ReadError,
            httpx.RemoteProtocolError,
            httpx.TimeoutException,
            httpx.PoolTimeout,
        ),
    )


async def provider_get(
    provider: str,
    url: str,
    *,
    params: dict[str, Any] | None = None,
    headers: dict[str, str] | None = None,
    timeout: float | None = None,
    follow_redirects: bool = True,
) -> httpx.Response:
    """GET with per-provider queueing, retry-after handling, and bounded retries."""
    settings = get_settings()
    max_retries = settings.external_api_default_max_retries
    base_delay = settings.external_api_backoff_base_seconds
    max_delay = settings.external_api_backoff_max_seconds
    limiter = await _limiter_for(provider)
    last_exc: Exception | None = None

    try:
        from app.services.search.diag_timing import enabled as diag_enabled, record_http

        if diag_enabled():
            record_http(provider)
    except Exception:
        pass

    for attempt in range(max_retries + 1):
        async with limiter.semaphore:
            await limiter.wait_turn()
            try:
                async with httpx.AsyncClient(
                    timeout=timeout,
                    follow_redirects=follow_redirects,
                    headers=headers,
                ) as client:
                    response = await client.get(url, params=params)
            except Exception as exc:
                if not _retryable_exception(exc) or attempt >= max_retries:
                    raise
                last_exc = exc
            else:
                if not _retryable_response(response) or attempt >= max_retries:
                    return response
                retry_after = _retry_after_seconds(response.headers.get("Retry-After"))
                if retry_after is not None:
                    await asyncio.sleep(min(retry_after, max_delay))
                    continue

        delay = min(max_delay, base_delay * (2**attempt))
        jitter = random.uniform(0, delay * 0.25) if delay > 0 else 0
        await asyncio.sleep(delay + jitter)

    if last_exc is not None:
        raise ProviderRequestError(str(last_exc)) from last_exc
    raise ProviderRequestError(f"{provider} request failed after retries.")


async def reset_provider_limiters_for_tests() -> None:
    async with _limiters_lock:
        _limiters.clear()
