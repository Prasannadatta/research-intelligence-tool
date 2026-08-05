"""Persist successful author analysis combinations."""

from __future__ import annotations

import logging
import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.author_analysis import AuthorAnalysisSearch

logger = logging.getLogger(__name__)


def build_combination_key(active_author_ids: list[str]) -> str:
    """Deterministic key from sorted active canonical author IDs."""
    sorted_ids = sorted(str(author_id).strip() for author_id in active_author_ids if author_id)
    return ",".join(sorted_ids)


def _provider_records_from_authors(authors: list[dict[str, Any]]) -> list[dict[str, str]]:
    records: list[dict[str, str]] = []
    seen: set[str] = set()
    for author in authors:
        key = f"{author.get('provider')}:{author.get('provider_author_id')}"
        if key in seen:
            continue
        seen.add(key)
        records.append(
            {
                "canonical_author_id": str(author.get("canonical_author_id") or ""),
                "provider": str(author.get("provider") or ""),
                "provider_author_id": str(author.get("provider_author_id") or ""),
            }
        )
    return records


async def upsert_author_analysis_search(
    session: AsyncSession,
    *,
    original_author_ids: list[str],
    active_authors: list[dict[str, Any]],
    mode: str,
    result_count: int,
) -> None:
    """
    Save or update a distinct author-analysis combination.

    Failures are logged and must not block the analysis response.
    """
    active_author_ids = [
        str(author.get("canonical_author_id") or "")
        for author in active_authors
        if author.get("canonical_author_id")
    ]
    if not active_author_ids:
        return

    combination_key = build_combination_key(active_author_ids)
    active_author_names = [
        str(author.get("display_name") or "").strip()
        for author in active_authors
        if author.get("display_name")
    ]
    provider_records = _provider_records_from_authors(active_authors)

    try:
        stmt = select(AuthorAnalysisSearch).where(
            AuthorAnalysisSearch.combination_key == combination_key
        )
        existing = (await session.execute(stmt)).scalar_one_or_none()

        if existing is None:
            session.add(
                AuthorAnalysisSearch(
                    id=uuid.uuid4(),
                    combination_key=combination_key,
                    original_author_ids=original_author_ids,
                    active_author_ids=active_author_ids,
                    active_author_names=active_author_names,
                    mode=mode,
                    provider_records=provider_records,
                    result_count=result_count,
                )
            )
        else:
            existing.original_author_ids = original_author_ids
            existing.active_author_ids = active_author_ids
            existing.active_author_names = active_author_names
            existing.mode = mode
            existing.provider_records = provider_records
            existing.result_count = result_count

        await session.commit()
    except Exception:
        logger.exception(
            "Failed to persist author analysis search for combination %s",
            combination_key,
        )
        await session.rollback()
