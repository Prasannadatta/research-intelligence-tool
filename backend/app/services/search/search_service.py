"""Unified search: authors via OpenAlex / ORCID / All (OA+ORCID); grants unchanged."""

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
    """Resolve an institution filter into a text affiliation for ORCID queries."""
    text = " ".join((affiliation or "").split())
    if text:
        return text
    inst = " ".join((institution_id or "").strip().split())
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


def _has_openalex_author_filters(
    *,
    institution_id: str | None,
    topic_id: str | None,
) -> bool:
    return bool(
        " ".join((institution_id or "").split())
        or " ".join((topic_id or "").split())
    )


def _drop_orcid_only_when_openalex_filters(
    results: list[Any],
    *,
    openalex_filters_active: bool,
) -> list[Any]:
    """
    When OpenAlex institution/topic filters are active, keep only rows that
    passed (or merged with) OpenAlex. ORCID-only hits cannot verify those filters.
    """
    if not openalex_filters_active:
        return results
    out: list[Any] = []
    for row in results:
        if not isinstance(row, dict):
            out.append(row)
            continue
        if row.get("source") == "openalex" or row.get("openalex_id"):
            out.append(row)
    return out


def _apply_openalex_enrichment(
    orcid_row: dict[str, Any],
    openalex_row: dict[str, Any],
) -> dict[str, Any]:
    """Attach OpenAlex fields onto an ORCID row when ORCID iDs match exactly."""
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
        # Keep ORCID as anchor; OpenAlex ids live in source_records / openalex_id.
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


def merge_authors_by_exact_orcid(results: list[Any]) -> list[Any]:
    """Deduplicate OpenAlex + ORCID rows using exact ORCID iD only — never by name."""
    rows = [row for row in results if isinstance(row, dict)]
    merged_by_orcid: dict[str, dict[str, Any]] = {}
    for row in rows:
        if row.get("source") != "orcid":
            continue
        key = normalize_orcid_id(row.get("orcid"))
        if key:
            merged_by_orcid[key] = dict(row)
    for row in rows:
        if row.get("source") != "openalex":
            continue
        key = normalize_orcid_id(row.get("orcid"))
        if key and key in merged_by_orcid:
            merged_by_orcid[key] = _apply_openalex_enrichment(merged_by_orcid[key], row)

    seen_orcid: set[str] = set()
    out: list[Any] = []
    for row in results:
        if not isinstance(row, dict):
            out.append(row)
            continue
        if row.get("source") == "orcid":
            key = normalize_orcid_id(row.get("orcid"))
            if not key or key in seen_orcid:
                continue
            seen_orcid.add(key)
            out.append(merged_by_orcid[key])
            continue
        if row.get("source") == "openalex":
            key = normalize_orcid_id(row.get("orcid"))
            # Drop OpenAlex row when the same ORCID already appears as an ORCID hit.
            if key and key in merged_by_orcid:
                continue
        out.append(row)
    return out


async def finalize_author_search_results(
    payload: dict[str, Any],
    *,
    openalex_filters_active: bool = False,
) -> dict[str, Any]:
    """
    Prepare author rows for the UI: exact-ORCID merge, then optional OA-filter drop.
    Does not write identity rows or call OpenAlex for ORCID hydration (that is selection-time).
    """
    results = list(payload.get("results") or [])
    if not results:
        return payload
    with diag_stage("exact_orcid_merge"):
        results = merge_authors_by_exact_orcid(results)
    results = _drop_orcid_only_when_openalex_filters(
        results,
        openalex_filters_active=openalex_filters_active,
    )
    return {**payload, "results": results}


async def run_search(
    *,
    query: str | None,
    entity_type: str,
    source: str = "all",
    limit: int = 20,
    cursor: str | None = None,
    institution_id: str | None = None,
    topic_id: str | None = None,
    search_mode: str = "auto",
    search_session_id: str | None = None,
    affiliation: str | None = None,
) -> dict[str, Any]:
    """
    Author sources:
      - all      → OpenAlex + ORCID in parallel, merged by exact ORCID before return
      - openalex → OpenAlex only
      - orcid    → ORCID only (lightweight; OpenAlex linking deferred to selection)
    arXiv is not part of author All. Identity DB writes happen on selection, not here.
    """
    provider_name = (source or "all").strip().lower()
    entity = (entity_type or "").strip().lower()
    openalex_filters_active = entity == "authors" and _has_openalex_author_filters(
        institution_id=institution_id,
        topic_id=topic_id,
    )

    # ORCID cannot apply OpenAlex institution/topic IDs. Ignore them for ORCID-only.
    effective_institution_id = institution_id
    effective_topic_id = topic_id
    if provider_name == "orcid":
        effective_institution_id = None
        effective_topic_id = None
        openalex_filters_active = False

    # Affiliation text is only useful when ORCID will be queried.
    # Under All + OpenAlex filters, skip ORCID entirely (cannot verify OA filters).
    needs_orcid = entity == "authors" and get_settings().orcid_configured and (
        provider_name == "orcid"
        or (provider_name == "all" and not openalex_filters_active)
    )
    affiliation_hint = None
    if needs_orcid:
        affiliation_hint = await _resolve_affiliation_hint(
            affiliation=affiliation,
            # Only use OA institution id as a soft ORCID affiliation hint under All
            # when we are actually querying ORCID without strict OA filters.
            institution_id=effective_institution_id if provider_name == "all" else None,
        )

    filters = {
        "institution_id": effective_institution_id,
        "topic_id": effective_topic_id,
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
                include_orcid=needs_orcid,
            )
        if entity == "authors":
            payload = await finalize_author_search_results(
                payload,
                openalex_filters_active=openalex_filters_active,
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

    if entity == "grants":
        return await _run_grants_search(
            provider=provider,
            provider_name=provider_name,
            entity=entity,
            query=query,
            cursor=cursor,
            limit=limit,
            filters=filters,
            search_session_id=search_session_id,
        )

    # Single author source: openalex | orcid | (legacy arxiv API still allowed).
    try:
        with diag_stage(f"provider_search:{provider_name}"):
            payload = await provider.search(
                entity=entity,
                query=query,
                cursor=cursor,
                limit=limit,
                filters=filters,
            )
    except (OpenAlexApiError, ArxivApiError, OrcidApiError) as exc:
        raise SearchServiceError(str(exc), status_code=exc.status_code) from exc
    except ValueError as exc:
        raise SearchServiceError(str(exc), status_code=400) from exc

    if entity == "authors":
        payload = await finalize_author_search_results(
            payload,
            openalex_filters_active=openalex_filters_active,
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


async def _run_author_all_sources(
    *,
    query: str | None,
    cursor: str | None,
    limit: int,
    filters: dict[str, Any],
    include_orcid: bool = True,
) -> dict[str, Any]:
    """OpenAlex + optional ORCID (no arXiv). Pagination cursor comes from OpenAlex."""
    openalex_provider = get_provider("openalex")
    orcid_provider = get_provider("orcid")
    orcid_enabled = bool(
        include_orcid
        and orcid_provider
        and orcid_provider.supports("authors")
        and get_settings().orcid_configured
    )

    async def _none_payload():
        return None

    oa_coro = (
        _safe_provider_search(
            openalex_provider,
            entity="authors",
            query=query,
            cursor=cursor,
            limit=limit,
            filters=filters,
        )
        if openalex_provider and openalex_provider.supports("authors")
        else _none_payload()
    )

    # ORCID only on the first page — later pages paginate OpenAlex only.
    orcid_coro = (
        _safe_provider_search(
            orcid_provider,
            entity="authors",
            query=query,
            cursor=None,
            limit=limit,
            filters=filters,
        )
        if orcid_enabled and _is_first_page(cursor)
        else _none_payload()
    )

    oa_payload, orcid_payload = await asyncio.gather(oa_coro, orcid_coro)
    oa_results = list((oa_payload or {}).get("results") or [])
    orcid_list = list((orcid_payload or {}).get("results") or [])

    # OpenAlex first, then ORCID — finalize_author_search_results merges by exact ORCID.
    combined = oa_results + orcid_list
    return {
        "query": normalize_orcid_id(query) or " ".join((query or "").split()),
        "entity_type": "authors",
        "source": "all",
        "results": combined,
        "next_cursor": (oa_payload or {}).get("next_cursor"),
        "has_more": bool((oa_payload or {}).get("has_more")),
    }


async def _run_all_sources_search(
    *,
    entity: str,
    query: str | None,
    cursor: str | None,
    limit: int,
    filters: dict[str, Any],
    search_session_id: str | None,
    include_orcid: bool = True,
) -> dict[str, Any]:
    del search_session_id

    if entity == "authors":
        return await _run_author_all_sources(
            query=query,
            cursor=cursor,
            limit=limit,
            filters=filters,
            include_orcid=include_orcid,
        )

    providers = [
        provider for provider in PROVIDERS.values() if provider.supports(entity)
    ]
    if not providers:
        raise SearchServiceError(
            "No search sources are available for this entity.",
            status_code=400,
        )
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


async def _run_grants_search(
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
