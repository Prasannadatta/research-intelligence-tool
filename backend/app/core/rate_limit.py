"""Simple in-memory rate limiter for authentication endpoints."""

from __future__ import annotations

import time
from collections import defaultdict, deque

from fastapi import HTTPException, Request, status

_attempts: dict[str, deque[float]] = defaultdict(deque)

LOGIN_LIMIT = 10
LOGIN_WINDOW_SECONDS = 15 * 60


def _client_ip(request: Request) -> str:
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",")[0].strip() or "unknown"
    if request.client and request.client.host:
        return request.client.host
    return "unknown"


def enforce_auth_rate_limit(
    request: Request,
    *,
    action: str,
    limit: int = LOGIN_LIMIT,
    window_seconds: int = LOGIN_WINDOW_SECONDS,
) -> None:
    key = f"{action}:{_client_ip(request)}"
    now = time.monotonic()
    bucket = _attempts[key]
    cutoff = now - window_seconds
    while bucket and bucket[0] < cutoff:
        bucket.popleft()
    if len(bucket) >= limit:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Too many attempts. Please try again later.",
        )
    bucket.append(now)
