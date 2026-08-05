"""Grant-number autocomplete suggestions."""

from __future__ import annotations

import logging
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.db.models.work_persistence import WorkGrantMatch
from app.integrations.openalex.grant_number import normalize_grant_number as oa_normalize
from app.integrations.openalex.grant_search import resolve_awards_for_grant_number
from app.services.work_persistence.normalization import normalize_grant_number


logger = logging.getLogger(__name__)

SUPPORTED_PROVIDERS = frozenset({"openalex", "arxiv"})


class GrantSuggestionsError(Exception):
    def __init__(self, message: str, *, status_code: int = 400) -> None:
        super().__init__(message)
        self.status_code = status_code


def _display_grant_number(raw: str | None, normalized: str) -> str:
    text = " ".join(str(raw or "").split()).strip()
    return text or normalized.upper()


def _funder_from_metadata(raw_metadata: Any) -> str | None:
    if not isinstance(raw_metadata, dict):
        return None
    for key in ("funder_name", "funder"):
        value = raw_metadata.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
        if isinstance(value, dict):
            name = value.get("display_name") or value.get("name")
            if isinstance(name, str) and name.strip():
                return name.strip()
    matched = raw_metadata.get("matched_grant")
    if isinstance(matched, dict):
        name = matched.get("funder_name")
        if isinstance(name, str) and name.strip():
            return name.strip()
    grants = raw_metadata.get("grants")
    if isinstance(grants, list):
        for grant in grants:
            if isinstance(grant, dict):
                name = grant.get("funder_name")
                if isinstance(name, str) and name.strip():
                    return name.strip()
    return None


def _rank_suggestion(normalized: str, prefix: str) -> tuple[int, int, str]:
    """Exact > prefix; shorter normalized ids next; stable by grant number."""
    if normalized == prefix:
        exact = 0
    elif normalized.startswith(prefix):
        exact = 1
    else:
        exact = 2
    return (exact, len(normalized), normalized)


async def _suggestions_from_db(
    session: AsyncSession,
    *,
    provider: str,
    prefix: str,
    limit: int,
) -> list[dict[str, Any]]:
    if not prefix:
        return []

    stmt = (
        select(
            WorkGrantMatch.normalized_grant_number,
            WorkGrantMatch.provider,
            func.max(WorkGrantMatch.grant_number).label("grant_number"),
            func.max(WorkGrantMatch.verified).label("verified"),
            func.count(func.distinct(WorkGrantMatch.canonical_work_id)).label(
                "publication_count"
            ),
        )
        .where(
            WorkGrantMatch.provider == provider,
            WorkGrantMatch.normalized_grant_number.like(f"{prefix}%"),
        )
        .group_by(
            WorkGrantMatch.normalized_grant_number,
            WorkGrantMatch.provider,
        )
    )
    result = await session.execute(stmt)
    rows = result.all()

    # Optional funder lookup from any matching row's metadata.
    funder_stmt = (
        select(
            WorkGrantMatch.normalized_grant_number,
            WorkGrantMatch.raw_metadata,
        )
        .where(
            WorkGrantMatch.provider == provider,
            WorkGrantMatch.normalized_grant_number.like(f"{prefix}%"),
            WorkGrantMatch.raw_metadata.is_not(None),
        )
        .limit(limit * 5)
    )
    funder_rows = (await session.execute(funder_stmt)).all()
    funders: dict[str, str | None] = {}
    for row in funder_rows:
        key = str(row.normalized_grant_number or "")
        if key and key not in funders:
            funders[key] = _funder_from_metadata(row.raw_metadata)

    by_key: dict[str, dict[str, Any]] = {}
    for row in rows:
        normalized = str(row.normalized_grant_number or "").strip()
        if not normalized:
            continue
        key = f"{provider}:{normalized}"
        by_key[key] = {
            "grant_number": _display_grant_number(row.grant_number, normalized),
            "normalized_grant_number": normalized,
            "funder_name": funders.get(normalized),
            "provider": provider,
            "verified": bool(row.verified),
            "publication_count": int(row.publication_count or 0),
        }

    ranked = sorted(
        by_key.values(),
        key=lambda item: _rank_suggestion(item["normalized_grant_number"], prefix),
    )
    return ranked[:limit]


async def _suggestions_from_openalex(
    *,
    query: str,
    limit: int,
) -> list[dict[str, Any]]:
    settings = get_settings()
    if not settings.openalex_configured:
        return []

    grant = oa_normalize(query)
    try:
        awards = await resolve_awards_for_grant_number(grant, limit=max(limit * 2, 10))
    except Exception:
        logger.exception("OpenAlex grant suggestion lookup failed")
        return []

    items: list[dict[str, Any]] = []
    seen: set[str] = set()
    prefix = normalize_grant_number(query)
    for award in awards:
        if not isinstance(award, dict):
            continue
        award_id = award.get("funder_award_id")
        if not award_id:
            continue
        normalized = normalize_grant_number(str(award_id))
        if not normalized:
            continue
        if prefix and not (
            normalized == prefix or normalized.startswith(prefix)
        ):
            continue
        if normalized in seen:
            continue
        seen.add(normalized)

        funder_name = None
        funder = award.get("funder")
        if isinstance(funder, dict):
            name = funder.get("display_name")
            if isinstance(name, str) and name.strip():
                funder_name = name.strip()

        items.append(
            {
                "grant_number": _display_grant_number(str(award_id), normalized),
                "normalized_grant_number": normalized,
                "funder_name": funder_name,
                "provider": "openalex",
                "verified": True,
                "publication_count": award.get("funded_outputs_count"),
            }
        )

    ranked = sorted(
        items,
        key=lambda item: _rank_suggestion(item["normalized_grant_number"], prefix),
    )
    return ranked[:limit]


async def suggest_grant_numbers(
    session: AsyncSession | None,
    *,
    q: str,
    provider: str,
    limit: int = 10,
) -> dict[str, Any]:
    provider_key = str(provider or "").strip().lower()
    if provider_key not in SUPPORTED_PROVIDERS:
        raise GrantSuggestionsError(
            "Provider must be openalex or arxiv.",
            status_code=422,
        )

    cleaned = " ".join(str(q or "").split()).strip()
    if len(cleaned) < 2:
        raise GrantSuggestionsError(
            "Query must be at least 2 characters.",
            status_code=422,
        )

    page_limit = max(1, min(int(limit or 10), 10))
    prefix = normalize_grant_number(cleaned)

    items: list[dict[str, Any]] = []
    if session is not None and prefix:
        try:
            items = await _suggestions_from_db(
                session,
                provider=provider_key,
                prefix=prefix,
                limit=page_limit,
            )
        except Exception:
            logger.exception("Failed reading grant suggestions from database")
            items = []

    # Provider fallback only when DB has no matches, and only for the selected
    # provider when it supports grant discovery (OpenAlex Awards).
    if not items and provider_key == "openalex":
        items = await _suggestions_from_openalex(query=cleaned, limit=page_limit)

    # Deduplicate again by provider + normalized grant number.
    deduped: list[dict[str, Any]] = []
    seen_keys: set[str] = set()
    for item in items:
        key = f"{item.get('provider')}:{item.get('normalized_grant_number')}"
        if key in seen_keys:
            continue
        seen_keys.add(key)
        deduped.append(item)

    return {"items": deduped[:page_limit]}
