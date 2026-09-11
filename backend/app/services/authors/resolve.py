"""Resolve selected author search hits into canonical identity records."""

from __future__ import annotations

import logging
from typing import Any

from app.core.config import get_settings

logger = logging.getLogger(__name__)


async def resolve_selected_authors(
    provider_results: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Resolve selected provider author rows into canonical identity records."""
    settings = get_settings()
    if not settings.author_resolution_enabled:
        return list(provider_results)

    rows = [row for row in provider_results if isinstance(row, dict)]
    if not rows:
        return []

    from app.db.session import SessionLocal
    from app.services.author_resolution.service import resolve_author_page

    try:
        async with SessionLocal() as session:
            resolved = await resolve_author_page(session, rows)
        return list(resolved.get("results") or [])
    except Exception:
        logger.exception("Author selection resolution failed; returning provider rows")
        return rows
