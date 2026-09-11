"""Canonical work resolution and search-page orchestration."""

from __future__ import annotations

import copy
import hashlib
import json
import logging
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.db.models import CanonicalWork
from app.services.work_persistence.candidate import (
    WorkCandidate,
    candidate_from_provider_result,
)
from app.services.work_persistence.normalization import normalize_search_query
from app.services.work_persistence.repository import WorkPersistenceRepository

logger = logging.getLogger(__name__)


def build_provider_cache_key(
    *,
    provider: str,
    entity: str,
    normalized_query: str,
    filters: dict[str, Any] | None,
    cursor: str | None,
    limit: int,
) -> str:
    """Stable cache key; provider is always included so sources never share entries."""
    filters_payload = _stable_filters(filters)
    raw = "|".join(
        [
            provider.strip().lower(),
            entity.strip().lower(),
            normalized_query,
            json.dumps(filters_payload, sort_keys=True, separators=(",", ":")),
            cursor or "*",
            str(limit),
        ]
    )
    digest = hashlib.sha256(raw.encode("utf-8")).hexdigest()
    return f"{provider.strip().lower()}:{entity.strip().lower()}:{digest}"


def _stable_filters(filters: dict[str, Any] | None) -> dict[str, Any]:
    if not filters:
        return {}
    out: dict[str, Any] = {}
    for key in sorted(filters.keys()):
        value = filters[key]
        if value is None or value == "":
            continue
        out[key] = value
    return out


def serialize_work_result(
    *,
    canonical: CanonicalWork,
    provider_result: dict[str, Any],
    provider: str,
    provider_work_id: str,
) -> dict[str, Any]:
    """Frontend-compatible publication row with stable canonical UUID as result_id."""
    row = copy.deepcopy(provider_result)
    row["result_id"] = str(canonical.id)
    row["canonical_work_id"] = str(canonical.id)
    row["result_type"] = "work"
    row["source"] = provider
    if provider == "openalex":
        row["openalex_id"] = provider_work_id
        row.setdefault("source_id", provider_work_id)
    elif provider == "arxiv":
        row["source_id"] = provider_work_id
    row["source_records"] = [
        {
            "provider": provider,
            "provider_work_id": provider_work_id,
        }
    ]
    return row


class WorkPersistenceService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.repo = WorkPersistenceRepository(session)
        self.settings = get_settings()

    async def resolve_candidate(
        self,
        candidate: WorkCandidate,
    ) -> tuple[CanonicalWork, bool]:
        """
        Resolve or create a canonical work.

        Conservative merge priority:
        1. existing provider record
        2. same DOI
        3. same arXiv ID
        4. same PMID
        5. title + first author + year + month (all required; month precision
           must agree). Same title + year alone is never enough. When month is
           unavailable, prefer keeping possible duplicates.
        """
        existing_record = await self.repo.get_provider_record(
            candidate.provider,
            candidate.provider_work_id,
        )
        if existing_record is not None and existing_record.canonical_work is not None:
            canonical = existing_record.canonical_work
            # Refresh the provider snapshot and upsert grants additively. Do not
            # recreate the canonical work or wipe other providers' grant rows.
            await self.repo.upsert_provider_record(candidate, canonical)
            await self.persist_grants_from_raw_metadata(
                canonical_work_id=canonical.id,
                provider=candidate.provider,
                raw_metadata=candidate.raw_metadata,
            )
            return canonical, False

        canonical = None
        if candidate.doi:
            canonical = await self.repo.find_canonical_by_doi(candidate.doi)
        if canonical is None and candidate.arxiv_id:
            canonical = await self.repo.find_canonical_by_arxiv_id(candidate.arxiv_id)
        if canonical is None and candidate.pmid:
            canonical = await self.repo.find_canonical_by_pmid(candidate.pmid)
        if canonical is None:
            canonical = await self.repo.find_canonical_by_title_author_strong_timing(
                normalized_title=candidate.normalized_title,
                publication_year=candidate.publication_year,
                publication_month=candidate.publication_month,
                normalized_first_author=candidate.normalized_first_author,
            )

        created = False
        if canonical is None:
            canonical = await self.repo.create_canonical_work(candidate)
            created = True
        else:
            self.repo.enrich_canonical_work(canonical, candidate)

        await self.repo.upsert_provider_record(candidate, canonical)
        await self.repo.replace_work_authorships(
            canonical_work_id=canonical.id,
            provider=candidate.provider,
            provider_work_id=candidate.provider_work_id,
            raw_metadata=candidate.raw_metadata,
        )
        await self.persist_grants_from_raw_metadata(
            canonical_work_id=canonical.id,
            provider=candidate.provider,
            raw_metadata=candidate.raw_metadata,
        )
        return canonical, created

    async def persist_grants_from_raw_metadata(
        self,
        *,
        canonical_work_id: uuid.UUID,
        provider: str,
        raw_metadata: dict[str, Any] | None,
    ) -> int:
        """Upsert source-aware grant rows from a provider work snapshot.

        Additive only — never deletes existing WorkGrantMatch rows (including
        OpenAlex grants when a later arXiv/Scopus enrichment overlay is attached).
        """
        from app.services.work_persistence.normalization import normalize_grant_number

        if not isinstance(raw_metadata, dict):
            return 0

        pending: list[dict[str, Any]] = []
        seen_normalized: set[str] = set()
        grants = raw_metadata.get("grants")
        if isinstance(grants, list):
            for item in grants:
                if not isinstance(item, dict):
                    continue
                award_id = (
                    item.get("award_id")
                    or item.get("grant_number")
                    or item.get("funder_award_id")
                )
                if not award_id:
                    continue
                verified_default = provider == "openalex"
                match_default = (
                    "structured_award_relationship"
                    if provider == "openalex"
                    else "metadata_text_match"
                )
                cleaned = " ".join(str(award_id).split()).strip()
                normalized = normalize_grant_number(cleaned)
                if not cleaned or not normalized or normalized in seen_normalized:
                    continue
                seen_normalized.add(normalized)
                funder = item.get("funder_name") or item.get("funder")
                if isinstance(funder, dict):
                    funder = funder.get("display_name")
                grant_meta = {
                    "funder_name": " ".join(str(funder).split()) if funder else None,
                    "award_id": cleaned,
                    "provider": item.get("provider") or provider,
                    "verified": bool(item.get("verified", verified_default)),
                    "match_type": item.get("match_type") or match_default,
                }
                pending.append(
                    {
                        "grant_number": cleaned,
                        "normalized_grant_number": normalized,
                        "verified": bool(item.get("verified", verified_default)),
                        "match_type": item.get("match_type") or match_default,
                        "raw_metadata": grant_meta,
                    }
                )

        matched = raw_metadata.get("matched_grant_number")
        if matched:
            cleaned = " ".join(str(matched).split()).strip()
            normalized = normalize_grant_number(cleaned)
            if cleaned and normalized and normalized not in seen_normalized:
                seen_normalized.add(normalized)
                grant_match = (
                    raw_metadata.get("grant_match")
                    if isinstance(raw_metadata.get("grant_match"), dict)
                    else {}
                )
                verified_default = provider == "openalex"
                match_default = (
                    "structured_award_relationship"
                    if provider == "openalex"
                    else "metadata_text_match"
                )
                pending.append(
                    {
                        "grant_number": cleaned,
                        "normalized_grant_number": normalized,
                        "verified": bool(
                            grant_match.get("verified")
                            if grant_match.get("verified") is not None
                            else verified_default
                        ),
                        "match_type": str(grant_match.get("type") or match_default),
                        "raw_metadata": {
                            "award_id": cleaned,
                            "provider": provider,
                            **grant_match,
                        },
                    }
                )

        persisted = 0
        for row in pending:
            await self.repo.upsert_grant_match(
                canonical_work_id=canonical_work_id,
                provider=provider,
                grant_number=row["grant_number"],
                normalized_grant_number=row["normalized_grant_number"],
                verified=row["verified"],
                match_type=row["match_type"],
                matched_text=None,
                raw_metadata=row["raw_metadata"],
            )
            persisted += 1
        return persisted

    async def attach_enrichment_to_existing(
        self,
        *,
        canonical_work_id: uuid.UUID,
        candidate: WorkCandidate,
    ) -> CanonicalWork | None:
        """Upsert provider metadata onto an existing canonical work only.

        Never creates a new CanonicalWork row. Does not rewrite authorships —
        enrichment overlays store citation/journal/preprint fields on
        ProviderWorkRecord.raw_metadata keyed by provider.
        """
        canonical = await self.session.get(CanonicalWork, canonical_work_id)
        if canonical is None:
            return None

        # Trust only stable ID agreement when both sides have the identifier.
        if candidate.doi and canonical.doi and candidate.doi != canonical.doi:
            logger.info(
                "enrichment_doi_mismatch canonical=%s candidate_doi=%s work_doi=%s",
                canonical_work_id,
                candidate.doi,
                canonical.doi,
            )
            return None
        if (
            candidate.arxiv_id
            and canonical.arxiv_id
            and candidate.arxiv_id != canonical.arxiv_id
        ):
            logger.info(
                "enrichment_arxiv_mismatch canonical=%s candidate=%s work=%s",
                canonical_work_id,
                candidate.arxiv_id,
                canonical.arxiv_id,
            )
            return None

        self.repo.enrich_canonical_work(canonical, candidate)
        await self.repo.upsert_provider_record(candidate, canonical)
        return canonical

    async def get_cached_provider_response(
        self,
        *,
        provider: str,
        entity: str,
        query: str,
        filters: dict[str, Any] | None,
        cursor: str | None,
        limit: int,
    ) -> dict[str, Any] | None:
        if not self.settings.provider_search_cache_enabled:
            return None
        normalized_query = normalize_search_query(query, entity=entity)
        cache_key = build_provider_cache_key(
            provider=provider,
            entity=entity,
            normalized_query=normalized_query,
            filters=filters,
            cursor=cursor,
            limit=limit,
        )
        entry = await self.repo.get_cache_entry(cache_key)
        if entry is None:
            return None
        expires_at = entry.expires_at
        if expires_at.tzinfo is None:
            expires_at = expires_at.replace(tzinfo=timezone.utc)
        if expires_at <= datetime.now(timezone.utc):
            return None
        # Hard isolation: never serve another provider's cache.
        if entry.provider != provider.strip().lower() or entry.entity != entity.strip().lower():
            return None
        return copy.deepcopy(entry.response)

    async def store_provider_response(
        self,
        *,
        provider: str,
        entity: str,
        query: str,
        filters: dict[str, Any] | None,
        cursor: str | None,
        limit: int,
        response: dict[str, Any],
    ) -> None:
        if not self.settings.provider_search_cache_enabled:
            return
        normalized_query = normalize_search_query(query, entity=entity)
        cache_key = build_provider_cache_key(
            provider=provider,
            entity=entity,
            normalized_query=normalized_query,
            filters=filters,
            cursor=cursor,
            limit=limit,
        )
        ttl = self.settings.provider_search_cache_ttl_seconds
        expires_at = datetime.now(timezone.utc) + timedelta(seconds=ttl)
        await self.repo.upsert_cache_entry(
            cache_key=cache_key,
            provider=provider.strip().lower(),
            entity=entity.strip().lower(),
            normalized_query=normalized_query,
            filters=_stable_filters(filters),
            cursor=cursor,
            response=copy.deepcopy(response),
            expires_at=expires_at,
        )

    async def get_or_create_session(
        self,
        *,
        search_session_id: str | None,
        provider: str,
        entity: str,
        query: str,
        filters: dict[str, Any] | None,
    ):
        now = datetime.now(timezone.utc)
        if search_session_id:
            try:
                session_uuid = uuid.UUID(str(search_session_id))
            except (TypeError, ValueError):
                session_uuid = None
            if session_uuid is not None:
                existing = await self.repo.get_search_session(session_uuid)
                if existing is not None:
                    expires_at = existing.expires_at
                    if expires_at.tzinfo is None:
                        expires_at = expires_at.replace(tzinfo=timezone.utc)
                    if (
                        expires_at > now
                        and existing.provider == provider
                        and existing.entity == entity
                    ):
                        return existing

        ttl = self.settings.search_session_ttl_seconds
        return await self.repo.create_search_session(
            provider=provider,
            entity=entity,
            query=query or "",
            normalized_query=normalize_search_query(query, entity=entity),
            filters=_stable_filters(filters),
            expires_at=now + timedelta(seconds=ttl),
        )

    async def process_works_page(
        self,
        *,
        provider: str,
        entity: str,
        query: str,
        filters: dict[str, Any] | None,
        cursor: str | None,
        page_number: int,
        payload: dict[str, Any],
        search_session_id: str | None,
    ) -> dict[str, Any]:
        session_row = await self.get_or_create_session(
            search_session_id=search_session_id,
            provider=provider,
            entity=entity,
            query=query or "",
            filters=filters,
        )
        seen_ids = await self.repo.list_session_entity_ids(session_row.id)
        next_position = await self.repo.next_session_position(session_row.id)

        results_out: list[dict[str, Any]] = []
        for raw in list(payload.get("results") or []):
            if not isinstance(raw, dict):
                continue
            candidate = candidate_from_provider_result(raw, provider=provider)
            if candidate is None:
                continue

            canonical, _ = await self.resolve_candidate(candidate)

            if entity == "grants" and candidate.normalized_grant_number:
                verified = (
                    True
                    if candidate.grant_verified is None and provider == "openalex"
                    else bool(candidate.grant_verified)
                )
                match_type = candidate.grant_match_type
                if not match_type:
                    match_type = (
                        "structured_award_relationship"
                        if provider == "openalex"
                        else "metadata_text_match"
                    )
                if provider == "openalex":
                    verified = True
                    match_type = "structured_award_relationship"
                elif provider == "arxiv":
                    verified = False
                    match_type = "metadata_text_match"

                await self.repo.upsert_grant_match(
                    canonical_work_id=canonical.id,
                    provider=provider,
                    grant_number=candidate.grant_number or "",
                    normalized_grant_number=candidate.normalized_grant_number,
                    verified=verified,
                    match_type=match_type,
                    matched_text=candidate.grant_matched_text,
                    raw_metadata=candidate.raw_metadata,
                )

            if canonical.id in seen_ids:
                continue

            added = await self.repo.add_session_result(
                search_session_id=session_row.id,
                canonical_entity_id=canonical.id,
                position=next_position,
                first_seen_page=page_number,
            )
            if added is None:
                continue

            seen_ids.add(canonical.id)
            next_position += 1
            results_out.append(
                serialize_work_result(
                    canonical=canonical,
                    provider_result=raw,
                    provider=provider,
                    provider_work_id=candidate.provider_work_id,
                )
            )

        next_cursor = payload.get("next_cursor")
        has_more = bool(payload.get("has_more"))
        return {
            **payload,
            "results": results_out,
            "search_session_id": str(session_row.id),
            "next_cursor": next_cursor,
            "has_more": has_more,
            "pagination": {
                "next_cursor": next_cursor,
                "has_more": has_more,
            },
        }


async def persist_works_search_page(
    session: AsyncSession,
    *,
    provider: str,
    entity: str,
    query: str,
    filters: dict[str, Any] | None,
    cursor: str | None,
    limit: int,
    payload: dict[str, Any],
    search_session_id: str | None,
    from_cache: bool = False,
) -> dict[str, Any]:
    """Persist provider page results into canonical works + search session."""
    service = WorkPersistenceService(session)
    if not from_cache:
        await service.store_provider_response(
            provider=provider,
            entity=entity,
            query=query or "",
            filters=filters,
            cursor=cursor,
            limit=limit,
            response=payload,
        )

    page_number = 1
    if cursor and cursor not in ("*", ""):
        # Opaque cursors: treat non-first pages as page > 1 for provenance only.
        page_number = 2

    return await service.process_works_page(
        provider=provider,
        entity=entity,
        query=query or "",
        filters=filters,
        cursor=cursor,
        page_number=page_number,
        payload=payload,
        search_session_id=search_session_id,
    )
