"""Unified search service that selects exactly one provider."""

from __future__ import annotations

import logging
from typing import Any

from app.core.config import get_settings
from app.integrations.arxiv.client import ArxivApiError
from app.integrations.openalex.client import OpenAlexApiError
from app.services.search.providers import get_provider

logger = logging.getLogger(__name__)


class SearchServiceError(Exception):
    def __init__(self, message: str, *, status_code: int = 400) -> None:
        super().__init__(message)
        self.status_code = status_code


async def run_search(
    *,
    query: str | None,
    entity_type: str,
    source: str = "openalex",
    limit: int = 20,
    cursor: str | None = None,
    institution_id: str | None = None,
    topic_id: str | None = None,
    search_mode: str = "auto",
    known_author_ids: list[str] | None = None,
    search_session_id: str | None = None,
) -> dict[str, Any]:
    """
    Route to exactly one provider. Never falls back or mixes providers.

    Author pages optionally run provider-independent identity resolution.
    Works/grants pages optionally persist canonical works, sessions, and cache.
    """
    provider_name = (source or "openalex").strip().lower()
    entity = (entity_type or "").strip().lower()

    if provider_name == "all":
        raise SearchServiceError(
            "Combined source search is not available yet.",
            status_code=400,
        )

    provider = get_provider(provider_name)
    if provider is None:
        raise SearchServiceError(
            "Unsupported search source.",
            status_code=422,
        )
    if not provider.enabled:
        raise SearchServiceError(
            f"Search source '{provider_name}' is not enabled.",
            status_code=400,
        )
    if not provider.supports(entity):
        raise SearchServiceError(
            f"Source '{provider_name}' does not support entity_type '{entity}'.",
            status_code=400,
        )

    filters = {
        "institution_id": institution_id,
        "topic_id": topic_id,
        "search_mode": search_mode,
    }

    if entity in ("works", "grants"):
        return await _run_works_or_grants_search(
            provider=provider,
            provider_name=provider_name,
            entity=entity,
            query=query,
            cursor=cursor,
            limit=limit,
            filters=filters,
            search_session_id=search_session_id,
        )

    try:
        payload = await provider.search(
            entity=entity,
            query=query,
            cursor=cursor,
            limit=limit,
            filters=filters,
        )
    except (OpenAlexApiError, ArxivApiError) as exc:
        raise SearchServiceError(str(exc), status_code=exc.status_code) from exc
    except ValueError as exc:
        raise SearchServiceError(str(exc), status_code=400) from exc

    if entity == "authors":
        payload = await _maybe_resolve_authors(
            payload,
            known_author_ids=known_author_ids,
        )

    return payload


async def _run_works_or_grants_search(
    *,
    provider: Any,
    provider_name: str,
    entity: str,
    query: str | None,
    cursor: str | None,
    limit: int,
    filters: dict[str, Any],
    search_session_id: str | None,
) -> dict[str, Any]:
    settings = get_settings()
    from_cache = False
    payload: dict[str, Any] | None = None

    if settings.work_persistence_enabled and settings.provider_search_cache_enabled:
        try:
            from app.db.session import SessionLocal
            from app.services.work_persistence.service import WorkPersistenceService

            async with SessionLocal() as session:
                service = WorkPersistenceService(session)
                payload = await service.get_cached_provider_response(
                    provider=provider_name,
                    entity=entity,
                    query=query or "",
                    filters=filters,
                    cursor=cursor,
                    limit=limit,
                )
                if payload is not None:
                    from_cache = True
        except Exception:
            logger.exception("Provider search cache lookup failed; calling provider")
            payload = None

    if payload is None:
        try:
            payload = await provider.search(
                entity=entity,
                query=query,
                cursor=cursor,
                limit=limit,
                filters=filters,
            )
        except (OpenAlexApiError, ArxivApiError) as exc:
            raise SearchServiceError(str(exc), status_code=exc.status_code) from exc
        except ValueError as exc:
            raise SearchServiceError(str(exc), status_code=400) from exc

    if not settings.work_persistence_enabled:
        return payload

    try:
        from app.db.session import SessionLocal
        from app.services.work_persistence.service import persist_works_search_page

        async with SessionLocal() as session:
            persisted = await persist_works_search_page(
                session,
                provider=provider_name,
                entity=entity,
                query=query or "",
                filters=filters,
                cursor=cursor,
                limit=limit,
                payload=payload,
                search_session_id=search_session_id,
                from_cache=from_cache,
            )
            await session.commit()
            return persisted
    except Exception:
        logger.exception("Work persistence failed; returning provider rows")
        return payload


async def _maybe_resolve_authors(
    payload: dict[str, Any],
    *,
    known_author_ids: list[str] | None,
) -> dict[str, Any]:
    settings = get_settings()
    if not settings.author_resolution_enabled:
        return payload

    try:
        from app.db.session import SessionLocal
        from app.services.author_resolution.service import resolve_author_page

        async with SessionLocal() as session:
            resolved = await resolve_author_page(
                session,
                list(payload.get("results") or []),
                known_canonical_ids=set(known_author_ids or []),
            )
    except Exception:
        logger.exception("Author identity resolution failed; returning provider rows")
        return payload

    next_cursor = payload.get("next_cursor")
    has_more = bool(payload.get("has_more"))
    return {
        **payload,
        "results": resolved["results"],
        "items": resolved["items"],
        "updates": resolved["updates"],
        "pagination": {
            "next_cursor": next_cursor,
            "has_more": has_more,
        },
    }
