"""Unified search service that selects a provider and optionally fans out ORCID authors."""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from app.core.config import get_settings
from app.integrations.arxiv.client import ArxivApiError
from app.integrations.openalex.client import OpenAlexApiError
from app.integrations.orcid.client import OrcidApiError
from app.integrations.orcid.normalize import normalize_orcid_id
from app.services.search.providers import PROVIDERS, get_provider

try:
    from app.services.search.diag_timing import enabled as diag_enabled, stage as diag_stage
except ImportError:  # pragma: no cover
    def diag_enabled() -> bool:
        return False

    from contextlib import contextmanager

    @contextmanager
    def diag_stage(_name: str):
        yield

logger = logging.getLogger(__name__)


class SearchServiceError(Exception):
    def __init__(self, message: str, *, status_code: int = 400) -> None:
        super().__init__(message)
        self.status_code = status_code


def _is_first_page(cursor: str | None) -> bool:
    return cursor is None or str(cursor).strip() in {"", "*"}


async def _resolve_affiliation_hint(
    *,
    affiliation: str | None,
    institution_id: str | None,
) -> str | None:
    text = " ".join((affiliation or "").split())
    if text:
        return text
    inst = " ".join((institution_id or "").split())
    if not inst:
        return None
    from app.integrations.openalex.filters import (
        get_institution_display_name,
        is_valid_institution_id,
    )

    if not is_valid_institution_id(inst):
        return inst
    try:
        name = await get_institution_display_name(inst)
    except Exception:
        logger.warning("orcid_affiliation_lookup_failed institution_id=%s", inst)
        return None
    return name


def _is_direct_orcid_query(query: str | None) -> bool:
    return bool(normalize_orcid_id(query))


async def _orcid_author_rows(
    *,
    query: str | None,
    limit: int,
    filters: dict[str, Any],
) -> list[dict[str, Any]]:
    try:
        from app.services.search.orcid_provider import search_orcid_author_results

        return await search_orcid_author_results(
            query=query,
            limit=limit,
            filters=filters,
            enrich=False,
        )
    except Exception:
        logger.warning("orcid_author_sidecar_failed")
        return []


def _append_orcid_rows(
    payload: dict[str, Any],
    orcid_rows: list[dict[str, Any]],
) -> dict[str, Any]:
    if not orcid_rows:
        return payload
    existing = list(payload.get("results") or [])
    seen: set[str] = set()
    for row in existing:
        if isinstance(row, dict) and row.get("source") == "orcid":
            key = normalize_orcid_id(row.get("orcid"))
            if key:
                seen.add(key)
    extra = []
    for row in orcid_rows:
        key = normalize_orcid_id(row.get("orcid"))
        if not key or key in seen:
            continue
        seen.add(key)
        extra.append(row)
    if not extra:
        return payload
    return {**payload, "results": existing + extra}


def _apply_openalex_enrichment(
    orcid_row: dict[str, Any],
    openalex_row: dict[str, Any],
) -> dict[str, Any]:
    """Attach OpenAlex identity onto an ORCID-anchored author row."""
    orcid = normalize_orcid_id(orcid_row.get("orcid"))
    oa_orcid = normalize_orcid_id(openalex_row.get("orcid"))
    if not orcid or orcid != oa_orcid:
        return orcid_row
    openalex_id = openalex_row.get("openalex_id")
    merged = {
        **orcid_row,
        "openalex_id": openalex_id or orcid_row.get("openalex_id"),
        "works_count": openalex_row.get("works_count")
        if openalex_row.get("works_count") is not None
        else orcid_row.get("works_count"),
        "cited_by_count": openalex_row.get("cited_by_count")
        if openalex_row.get("cited_by_count") is not None
        else orcid_row.get("cited_by_count"),
        "topics": openalex_row.get("topics") or orcid_row.get("topics") or [],
        "alternative_names": openalex_row.get("alternative_names")
        or orcid_row.get("alternative_names")
        or [],
        "source": "orcid",
        "orcid": orcid,
    }
    if not merged.get("primary_institution") and openalex_row.get("primary_institution"):
        merged["primary_institution"] = openalex_row.get("primary_institution")
    source_records = [
        {"provider": "orcid", "provider_author_id": orcid},
    ]
    if openalex_id:
        source_records.append(
            {"provider": "openalex", "provider_author_id": openalex_id}
        )
    merged["source_records"] = source_records
    return merged


def _link_results_by_exact_orcid(results: list[Any]) -> list[Any]:
    """Dedupe OpenAlex+ORCID rows only when the ORCID iD matches exactly."""
    rows = [row for row in results if isinstance(row, dict)]
    merged: dict[str, dict[str, Any]] = {}
    for row in rows:
        if row.get("source") != "orcid":
            continue
        key = normalize_orcid_id(row.get("orcid"))
        if key:
            merged[key] = dict(row)
    for row in rows:
        if row.get("source") != "openalex":
            continue
        key = normalize_orcid_id(row.get("orcid"))
        if key and key in merged:
            merged[key] = _apply_openalex_enrichment(merged[key], row)
    seen: set[str] = set()
    out: list[Any] = []
    for row in results:
        if not isinstance(row, dict):
            out.append(row)
            continue
        if row.get("source") == "orcid":
            key = normalize_orcid_id(row.get("orcid"))
            if not key or key in seen:
                continue
            seen.add(key)
            out.append(merged[key])
            continue
        if row.get("source") == "openalex":
            key = normalize_orcid_id(row.get("orcid"))
            if key and key in merged:
                continue
        out.append(row)
    return out


async def _hydrate_orcid_rows_from_openalex(
    results: list[Any],
) -> list[Any]:
    """Look up missing OpenAlex records by exact ORCID. Never matches by name."""
    from app.integrations.openalex.unified_search import search_openalex_authors_by_orcid

    known_oa = {
        normalize_orcid_id(row.get("orcid"))
        for row in results
        if isinstance(row, dict)
        and row.get("source") == "openalex"
        and row.get("openalex_id")
        and normalize_orcid_id(row.get("orcid"))
    }

    async def hydrate(row: Any) -> Any:
        if not isinstance(row, dict) or row.get("source") != "orcid":
            return row
        if row.get("openalex_id"):
            return row
        orcid = normalize_orcid_id(row.get("orcid"))
        if not orcid or orcid in known_oa:
            return row
        try:
            payload = await search_openalex_authors_by_orcid(orcid, limit=5)
        except Exception:
            logger.warning("openalex_orcid_enrichment_failed orcid=%s", orcid)
            return row
        for oa_row in payload.get("results") or []:
            if normalize_orcid_id(oa_row.get("orcid")) == orcid:
                return _apply_openalex_enrichment(row, oa_row)
        return row

    hydrated = await asyncio.gather(*[hydrate(row) for row in results])
    return list(hydrated)


async def _finalize_author_results(
    payload: dict[str, Any],
    *,
    known_author_ids: list[str] | None,
    hydrate_openalex: bool = False,
) -> dict[str, Any]:
    results = list(payload.get("results") or [])
    if results:
        if hydrate_openalex:
            with diag_stage("orcid_openalex_enrichment"):
                results = await _hydrate_orcid_rows_from_openalex(results)
        with diag_stage("exact_orcid_link"):
            results = _link_results_by_exact_orcid(results)
        payload = {**payload, "results": results}
    with diag_stage("canonical_resolution"):
        return await _maybe_resolve_authors(
            payload,
            known_author_ids=known_author_ids,
        )


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
    affiliation: str | None = None,
) -> dict[str, Any]:
    """
    Route to one primary provider, or fan out when source=all.

    Author searches also run ORCID in parallel when another source is selected.
    ORCID failures never fail the overall search.
    Candidates from different providers are concatenated, then linked only by
    exact ORCID — never by name.
    """
    provider_name = (source or "openalex").strip().lower()
    entity = (entity_type or "").strip().lower()

    affiliation_hint = None
    if entity == "authors":
        affiliation_hint = await _resolve_affiliation_hint(
            affiliation=affiliation,
            institution_id=institution_id,
        )

    filters = {
        "institution_id": institution_id,
        "topic_id": topic_id,
        "search_mode": search_mode,
        "affiliation": affiliation_hint,
    }

    if provider_name == "all":
        with diag_stage("provider_fanout:all"):
            payload = await _run_all_sources_search(
            entity=entity,
            query=query,
            cursor=cursor,
            limit=limit,
            filters=filters,
            search_session_id=search_session_id,
        )
        if entity == "authors":
            payload = await _finalize_author_results(
                payload,
                known_author_ids=known_author_ids,
                hydrate_openalex=_is_direct_orcid_query(query),
            )
        return payload

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

    run_orcid_sidecar = (
        entity == "authors"
        and provider_name != "orcid"
        and _is_first_page(cursor)
        and get_settings().orcid_configured
    )

    try:
        if run_orcid_sidecar:
            with diag_stage("provider_fanout:openalex+orcid_sidecar"):
                primary_payload, orcid_rows = await asyncio.gather(
                    provider.search(
                        entity=entity,
                        query=query,
                        cursor=cursor,
                        limit=limit,
                        filters=filters,
                    ),
                    _orcid_author_rows(query=query, limit=limit, filters=filters),
                )
        else:
            with diag_stage(f"provider_search:{provider_name}"):
                primary_payload = await provider.search(
                    entity=entity,
                    query=query,
                    cursor=cursor,
                    limit=limit,
                    filters=filters,
                )
            orcid_rows = []
    except (OpenAlexApiError, ArxivApiError, OrcidApiError) as exc:
        raise SearchServiceError(str(exc), status_code=exc.status_code) from exc
    except ValueError as exc:
        raise SearchServiceError(str(exc), status_code=400) from exc

    payload = _append_orcid_rows(primary_payload, orcid_rows)

    if entity == "authors":
        payload = await _finalize_author_results(
            payload,
            known_author_ids=known_author_ids,
            hydrate_openalex=_is_direct_orcid_query(query),
        )

    return payload


async def _safe_provider_search(
    provider: Any,
    *,
    entity: str,
    query: str | None,
    cursor: str | None,
    limit: int,
    filters: dict[str, Any],
) -> dict[str, Any] | None:
    try:
        with diag_stage(f"provider_search:{provider.id}"):
            return await provider.search(
                entity=entity,
                query=query,
                cursor=cursor,
                limit=limit,
                filters=filters,
            )
    except (OpenAlexApiError, ArxivApiError, OrcidApiError, ValueError):
        logger.warning(
            "combined_search_provider_failed provider=%s entity=%s",
            provider.id,
            entity,
        )
        return None
    except Exception:
        logger.exception("combined_search_provider_failed provider=%s", provider.id)
        return None


async def _run_all_sources_search(
    *,
    entity: str,
    query: str | None,
    cursor: str | None,
    limit: int,
    filters: dict[str, Any],
    search_session_id: str | None,
) -> dict[str, Any]:
    orcid_query = normalize_orcid_id(query) if entity == "authors" else None
    providers = [
        provider
        for provider in PROVIDERS.values()
        if provider.supports(entity)
        and not (orcid_query and provider.id == "arxiv")
    ]
    if not providers:
        raise SearchServiceError(
            "No search sources are available for this entity.",
            status_code=400,
        )

    if entity in ("works", "grants"):
        payloads = await asyncio.gather(
            *[
                _safe_provider_search(
                    provider,
                    entity=entity,
                    query=query,
                    cursor=cursor,
                    limit=limit,
                    filters=filters,
                )
                for provider in providers
            ]
        )
        combined: list[Any] = []
        next_cursor = None
        has_more = False
        for payload in payloads:
            if not payload:
                continue
            combined.extend(payload.get("results") or [])
            if payload.get("has_more"):
                has_more = True
            if next_cursor is None:
                next_cursor = payload.get("next_cursor")
        return {
            "query": " ".join((query or "").split()),
            "entity_type": entity,
            "source": "all",
            "results": combined,
            "next_cursor": next_cursor,
            "has_more": has_more,
        }

    if orcid_query:
        orcid_provider = get_provider("orcid")
        openalex_provider = get_provider("openalex")
        orcid_payload = None
        if orcid_provider and orcid_provider.supports("authors"):
            orcid_payload = await _safe_provider_search(
                orcid_provider,
                entity="authors",
                query=orcid_query,
                cursor=None,
                limit=limit,
                filters=filters,
            )
        oa_payload = None
        if openalex_provider and openalex_provider.supports("authors"):
            oa_payload = await _safe_provider_search(
                openalex_provider,
                entity="authors",
                query=orcid_query,
                cursor=cursor,
                limit=limit,
                filters=filters,
            )
        results = list((orcid_payload or {}).get("results") or []) + list(
            (oa_payload or {}).get("results") or []
        )
        return {
            "query": orcid_query,
            "entity_type": "authors",
            "source": "all",
            "results": results,
            "next_cursor": (oa_payload or {}).get("next_cursor"),
            "has_more": bool((oa_payload or {}).get("has_more")),
        }

    payloads = await asyncio.gather(
        *[
            _safe_provider_search(
                provider,
                entity="authors",
                query=query,
                cursor=cursor if provider.id != "orcid" else None,
                limit=limit,
                filters=filters,
            )
            for provider in providers
        ]
    )
    combined_rows: list[Any] = []
    next_cursor = None
    has_more = False
    for payload in payloads:
        if not payload:
            continue
        combined_rows.extend(payload.get("results") or [])
        if payload.get("source") == "openalex":
            next_cursor = payload.get("next_cursor")
            has_more = bool(payload.get("has_more"))
        elif payload.get("has_more") and next_cursor is None:
            next_cursor = payload.get("next_cursor")
            has_more = True
    return {
        "query": " ".join((query or "").split()),
        "entity_type": "authors",
        "source": "all",
        "results": combined_rows,
        "next_cursor": next_cursor,
        "has_more": has_more,
    }


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
    results = list(payload.get("results") or [])

    if not settings.author_resolution_enabled:
        return payload

    try:
        from app.db.session import SessionLocal
        from app.services.author_resolution.service import resolve_author_page

        async with SessionLocal() as session:
            resolved = await resolve_author_page(
                session,
                results,
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
