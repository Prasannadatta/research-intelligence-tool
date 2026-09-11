"""Enrich existing OpenAlex canonical works with arXiv / Scopus metadata.

OpenAlex remains the authoritative corpus. This module never creates new
CanonicalWork rows — it only upserts ProviderWorkRecord overlays matched by
DOI, arXiv id, or stable provider ids, and caches responses so Analyze page
loads are not blocked on provider HTTP.
"""

from __future__ import annotations

import asyncio
import logging
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any, Iterable

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.config import get_settings
from app.db.models import CanonicalWork, ProviderWorkRecord
from app.integrations.arxiv.client import fetch_arxiv_works_by_ids
from app.integrations.elsevier.cited_by import (
    parse_scopus_abstract_enrichment,
    scopus_enrichment_as_provider_result,
)
from app.integrations.elsevier.client import ElsevierApiError, ElsevierClient, elsevier_configured
from app.services.work_persistence.candidate import candidate_from_provider_result
from app.services.work_persistence.normalization import (
    arxiv_id_from_doi,
    normalize_arxiv_id,
    normalize_doi,
)
from app.services.work_persistence.service import WorkPersistenceService

logger = logging.getLogger(__name__)

ENRICHMENT_ENTITY = "work_enrichment"
# Prefer OpenAlex for the single display citation_count; never sum/max providers.
CITATION_PROVIDER_PREFERENCE = ("openalex", "scopus", "arxiv")


@dataclass
class EnrichmentMetrics:
    provider_calls: dict[str, int] = field(
        default_factory=lambda: {"arxiv": 0, "scopus": 0, "openalex": 0, "orcid": 0}
    )
    cache_hits: dict[str, int] = field(
        default_factory=lambda: {"arxiv": 0, "scopus": 0}
    )
    enriched: dict[str, int] = field(
        default_factory=lambda: {"arxiv": 0, "scopus": 0}
    )
    skipped: dict[str, int] = field(
        default_factory=lambda: {
            "no_match_key": 0,
            "fresh_provider_record": 0,
            "not_found": 0,
            "error": 0,
            "disabled": 0,
        }
    )
    created_canonical_works: int = 0
    elapsed_ms: dict[str, float] = field(
        default_factory=lambda: {"arxiv": 0.0, "scopus": 0.0, "total": 0.0}
    )
    works_considered: int = 0
    works_attempted: int = 0

    def as_dict(self) -> dict[str, Any]:
        return {
            "provider_calls": dict(self.provider_calls),
            "cache_hits": dict(self.cache_hits),
            "enriched": dict(self.enriched),
            "skipped": dict(self.skipped),
            "created_canonical_works": self.created_canonical_works,
            "elapsed_ms": {key: round(value, 2) for key, value in self.elapsed_ms.items()},
            "works_considered": self.works_considered,
            "works_attempted": self.works_attempted,
        }


def preferred_citation_count(citations_by_provider: dict[str, int | None]) -> int | None:
    """Pick one display citation count without merging conflicting providers."""
    cleaned: dict[str, int] = {}
    for provider, value in citations_by_provider.items():
        if value is None:
            continue
        try:
            count = int(value)
        except (TypeError, ValueError):
            continue
        if count >= 0:
            cleaned[str(provider).strip().lower()] = count
    for provider in CITATION_PROVIDER_PREFERENCE:
        if provider in cleaned:
            return cleaned[provider]
    for value in cleaned.values():
        return value
    return None


def _aware(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value


def _record_is_fresh(record: ProviderWorkRecord | None, *, ttl_seconds: int) -> bool:
    if record is None or record.retrieved_at is None:
        return False
    retrieved = _aware(record.retrieved_at)
    if retrieved is None:
        return False
    return retrieved + timedelta(seconds=max(int(ttl_seconds), 1)) > datetime.now(timezone.utc)


class PublicationEnrichmentService:
    """Background enrich-only overlays for stored Analyze corpus works."""

    def __init__(
        self,
        session: AsyncSession,
        *,
        elsevier_client: ElsevierClient | None = None,
    ) -> None:
        self.session = session
        self.settings = get_settings()
        self._elsevier = elsevier_client or ElsevierClient()
        self.persistence = WorkPersistenceService(session)
        self.metrics = EnrichmentMetrics()

    async def enrich_canonical_works(
        self,
        work_ids: Iterable[uuid.UUID | str],
        *,
        max_works: int | None = None,
    ) -> EnrichmentMetrics:
        started = time.perf_counter()
        if not self.settings.publication_enrichment_enabled:
            self.metrics.skipped["disabled"] += 1
            self.metrics.elapsed_ms["total"] = (time.perf_counter() - started) * 1000
            return self.metrics

        unique: list[uuid.UUID] = []
        seen: set[uuid.UUID] = set()
        for value in work_ids:
            try:
                work_id = value if isinstance(value, uuid.UUID) else uuid.UUID(str(value))
            except (TypeError, ValueError):
                continue
            if work_id in seen:
                continue
            seen.add(work_id)
            unique.append(work_id)

        limit = max_works
        if limit is None:
            limit = int(self.settings.publication_enrichment_max_works_per_job)
        unique = unique[: max(int(limit), 0)]
        self.metrics.works_considered = len(unique)
        if not unique:
            self.metrics.elapsed_ms["total"] = (time.perf_counter() - started) * 1000
            return self.metrics

        works = await self._load_works(unique)
        self.metrics.works_attempted = len(works)

        await self._enrich_arxiv(works)
        await self._enrich_scopus(works)

        self.metrics.elapsed_ms["total"] = (time.perf_counter() - started) * 1000
        logger.info(
            "publication_enrichment_done works=%s enriched=%s calls=%s cache_hits=%s "
            "created=%s elapsed_ms=%s",
            self.metrics.works_attempted,
            self.metrics.enriched,
            self.metrics.provider_calls,
            self.metrics.cache_hits,
            self.metrics.created_canonical_works,
            self.metrics.elapsed_ms,
        )
        return self.metrics

    async def enrich_authors_corpus(
        self,
        authors: list[dict[str, Any]],
        *,
        max_works: int | None = None,
    ) -> EnrichmentMetrics:
        """Enrich works in the stored Analyze membership corpus for selected authors."""
        from app.services.analysis.publication_corpus import load_stored_publication_filter_items

        loaded = await load_stored_publication_filter_items(self.session, authors)
        return await self.enrich_canonical_works(
            loaded.get("work_ids") or [],
            max_works=max_works,
        )

    async def _load_works(self, work_ids: list[uuid.UUID]) -> list[CanonicalWork]:
        result = await self.session.execute(
            select(CanonicalWork)
            .where(CanonicalWork.id.in_(work_ids))
            .options(selectinload(CanonicalWork.provider_records))
        )
        by_id = {work.id: work for work in result.scalars().unique().all()}
        return [by_id[work_id] for work_id in work_ids if work_id in by_id]

    def _provider_record(
        self,
        work: CanonicalWork,
        provider: str,
    ) -> ProviderWorkRecord | None:
        for record in work.provider_records or []:
            if record.provider == provider:
                return record
        return None

    def _stable_arxiv_id(self, work: CanonicalWork) -> str | None:
        if work.arxiv_id:
            return normalize_arxiv_id(work.arxiv_id)
        from_doi = arxiv_id_from_doi(work.doi)
        if from_doi:
            return from_doi
        for record in work.provider_records or []:
            raw = record.raw_metadata if isinstance(record.raw_metadata, dict) else {}
            candidate = normalize_arxiv_id(
                raw.get("arxiv_id") or (raw.get("source_id") if record.provider == "arxiv" else None)
            )
            if candidate:
                return candidate
            from_raw_doi = arxiv_id_from_doi(raw.get("doi") if isinstance(raw.get("doi"), str) else None)
            if from_raw_doi:
                return from_raw_doi
        return None

    async def _cache_get(
        self,
        *,
        provider: str,
        query: str,
    ) -> dict[str, Any] | None:
        return await self.persistence.get_cached_provider_response(
            provider=provider,
            entity=ENRICHMENT_ENTITY,
            query=query,
            filters=None,
            cursor=None,
            limit=1,
        )

    async def _cache_set(
        self,
        *,
        provider: str,
        query: str,
        response: dict[str, Any],
        negative: bool = False,
    ) -> None:
        await self.persistence.store_provider_response(
            provider=provider,
            entity=ENRICHMENT_ENTITY,
            query=query,
            filters=None,
            cursor=None,
            limit=1,
            response=response,
        )
        ttl = int(
            self.settings.publication_enrichment_negative_ttl_seconds
            if negative
            else self.settings.publication_enrichment_ttl_seconds
        )
        from app.services.work_persistence.normalization import normalize_search_query
        from app.services.work_persistence.service import build_provider_cache_key

        cache_key = build_provider_cache_key(
            provider=provider,
            entity=ENRICHMENT_ENTITY,
            normalized_query=normalize_search_query(query, entity=ENRICHMENT_ENTITY),
            filters=None,
            cursor=None,
            limit=1,
        )
        row = await self.persistence.repo.get_cache_entry(cache_key)
        if row is not None:
            row.expires_at = datetime.now(timezone.utc) + timedelta(seconds=ttl)
            await self.session.flush()

    async def _enrich_arxiv(self, works: list[CanonicalWork]) -> None:
        if not self.settings.arxiv_configured:
            return

        ttl = int(self.settings.publication_enrichment_ttl_seconds)
        batch_size = int(self.settings.publication_enrichment_arxiv_batch_size)
        targets: list[tuple[CanonicalWork, str]] = []
        for work in works:
            arxiv_id = self._stable_arxiv_id(work)
            if not arxiv_id:
                continue
            existing = self._provider_record(work, "arxiv")
            if _record_is_fresh(existing, ttl_seconds=ttl):
                self.metrics.skipped["fresh_provider_record"] += 1
                self.metrics.cache_hits["arxiv"] += 1
                continue
            targets.append((work, arxiv_id))

        if not targets:
            return

        by_id: dict[str, list[CanonicalWork]] = {}
        for work, arxiv_id in targets:
            by_id.setdefault(arxiv_id, []).append(work)

        ids = list(by_id.keys())
        for start in range(0, len(ids), batch_size):
            chunk = ids[start : start + batch_size]
            # Per-id cache first.
            need_fetch: list[str] = []
            cached_rows: dict[str, dict[str, Any]] = {}
            for arxiv_id in chunk:
                cached = await self._cache_get(provider="arxiv", query=f"arxiv:{arxiv_id}")
                if cached is None:
                    need_fetch.append(arxiv_id)
                    continue
                self.metrics.cache_hits["arxiv"] += 1
                if cached.get("status") == "not_found":
                    self.metrics.skipped["not_found"] += 1
                    continue
                result = cached.get("result")
                if isinstance(result, dict):
                    cached_rows[arxiv_id] = result

            if need_fetch:
                t0 = time.perf_counter()
                try:
                    self.metrics.provider_calls["arxiv"] += 1
                    fetched = await fetch_arxiv_works_by_ids(need_fetch)
                except Exception as exc:  # noqa: BLE001 — soft-fail enrichment
                    self.metrics.skipped["error"] += len(need_fetch)
                    logger.warning(
                        "publication_enrichment_arxiv_failed count=%s error=%s",
                        len(need_fetch),
                        type(exc).__name__,
                    )
                    fetched = []
                self.metrics.elapsed_ms["arxiv"] += (time.perf_counter() - t0) * 1000

                found_ids: set[str] = set()
                for row in fetched:
                    if not isinstance(row, dict):
                        continue
                    rid = normalize_arxiv_id(
                        row.get("arxiv_id") or row.get("source_id")
                    )
                    if not rid:
                        continue
                    found_ids.add(rid)
                    await self._cache_set(
                        provider="arxiv",
                        query=f"arxiv:{rid}",
                        response={"status": "success", "result": row},
                    )
                    cached_rows[rid] = row
                for missing in need_fetch:
                    if missing in found_ids:
                        continue
                    await self._cache_set(
                        provider="arxiv",
                        query=f"arxiv:{missing}",
                        response={"status": "not_found", "result": None},
                        negative=True,
                    )
                    self.metrics.skipped["not_found"] += 1

            before_count = await self._canonical_work_count()
            for arxiv_id, row in cached_rows.items():
                for work in by_id.get(arxiv_id, []):
                    await self._attach_row(work, provider="arxiv", row=row)
            after_count = await self._canonical_work_count()
            if after_count > before_count:
                self.metrics.created_canonical_works += after_count - before_count
            await self.session.commit()

    async def _enrich_scopus(self, works: list[CanonicalWork]) -> None:
        if not elsevier_configured():
            return

        ttl = int(self.settings.publication_enrichment_ttl_seconds)
        concurrency = max(int(self.settings.publication_enrichment_concurrency), 1)
        semaphore = asyncio.Semaphore(concurrency)
        targets: list[tuple[CanonicalWork, str]] = []
        for work in works:
            doi = normalize_doi(work.doi)
            if not doi:
                self.metrics.skipped["no_match_key"] += 1
                continue
            existing = self._provider_record(work, "scopus")
            if _record_is_fresh(existing, ttl_seconds=ttl):
                self.metrics.skipped["fresh_provider_record"] += 1
                self.metrics.cache_hits["scopus"] += 1
                continue
            targets.append((work, doi))

        if not targets:
            return

        async def _one(work: CanonicalWork, doi: str) -> None:
            async with semaphore:
                await self._enrich_one_scopus(work, doi)

        before_count = await self._canonical_work_count()
        await asyncio.gather(*[_one(work, doi) for work, doi in targets])
        after_count = await self._canonical_work_count()
        if after_count > before_count:
            self.metrics.created_canonical_works += after_count - before_count
        await self.session.commit()

    async def _enrich_one_scopus(self, work: CanonicalWork, doi: str) -> None:
        cache_query = f"doi:{doi}"
        cached = await self._cache_get(provider="scopus", query=cache_query)
        if cached is not None:
            self.metrics.cache_hits["scopus"] += 1
            if cached.get("status") == "not_found":
                self.metrics.skipped["not_found"] += 1
                return
            result = cached.get("result")
            if isinstance(result, dict):
                await self._attach_row(work, provider="scopus", row=result)
            return

        t0 = time.perf_counter()
        try:
            self.metrics.provider_calls["scopus"] += 1
            response = await self._elsevier.get_abstract_doi(doi, view="META")
        except ElsevierApiError as exc:
            self.metrics.skipped["error"] += 1
            logger.warning(
                "publication_enrichment_scopus_api_error doi=%s status=%s",
                doi,
                getattr(exc, "status_code", None),
            )
            self.metrics.elapsed_ms["scopus"] += (time.perf_counter() - t0) * 1000
            return
        except Exception as exc:  # noqa: BLE001
            self.metrics.skipped["error"] += 1
            logger.warning(
                "publication_enrichment_scopus_failed doi=%s error=%s",
                doi,
                type(exc).__name__,
            )
            self.metrics.elapsed_ms["scopus"] += (time.perf_counter() - t0) * 1000
            return
        self.metrics.elapsed_ms["scopus"] += (time.perf_counter() - t0) * 1000

        if response.status_code == 404:
            await self._cache_set(
                provider="scopus",
                query=cache_query,
                response={"status": "not_found", "result": None},
                negative=True,
            )
            self.metrics.skipped["not_found"] += 1
            return
        if response.status_code != 200:
            self.metrics.skipped["error"] += 1
            return

        enrichment = parse_scopus_abstract_enrichment(response.json())
        if enrichment is None or not (enrichment.scopus_id or enrichment.eid):
            await self._cache_set(
                provider="scopus",
                query=cache_query,
                response={"status": "not_found", "result": None},
                negative=True,
            )
            self.metrics.skipped["not_found"] += 1
            return

        row = scopus_enrichment_as_provider_result(
            enrichment,
            fallback_title=work.title,
        )
        await self._cache_set(
            provider="scopus",
            query=cache_query,
            response={"status": "success", "result": row},
        )
        await self._attach_row(work, provider="scopus", row=row)

    async def _attach_row(
        self,
        work: CanonicalWork,
        *,
        provider: str,
        row: dict[str, Any],
    ) -> None:
        candidate = candidate_from_provider_result(row, provider=provider)
        if candidate is None:
            self.metrics.skipped["error"] += 1
            return
        attached = await self.persistence.attach_enrichment_to_existing(
            canonical_work_id=work.id,
            candidate=candidate,
        )
        if attached is None:
            self.metrics.skipped["error"] += 1
            return
        self.metrics.enriched[provider] = self.metrics.enriched.get(provider, 0) + 1

    async def _canonical_work_count(self) -> int:
        result = await self.session.execute(select(CanonicalWork.id))
        return len(result.all())


async def enrich_selected_authors_publications(
    session: AsyncSession,
    authors: list[dict[str, Any]],
    *,
    max_works: int | None = None,
) -> dict[str, Any]:
    """Soft-fail entry point used by Analyze/Insights background jobs."""
    try:
        metrics = await PublicationEnrichmentService(session).enrich_authors_corpus(
            authors,
            max_works=max_works,
        )
        # Persist overlays before Insights/stats read the stored corpus.
        await session.commit()
        return metrics.as_dict()
    except Exception:  # noqa: BLE001 — never fail the parent analytics job
        logger.exception("publication_enrichment_job_soft_failed")
        try:
            await session.rollback()
        except Exception:  # noqa: BLE001
            logger.exception("publication_enrichment_rollback_failed")
        return {
            "provider_calls": {"arxiv": 0, "scopus": 0},
            "cache_hits": {"arxiv": 0, "scopus": 0},
            "enriched": {"arxiv": 0, "scopus": 0},
            "skipped": {"error": 1},
            "created_canonical_works": 0,
            "elapsed_ms": {"total": 0.0},
            "works_considered": 0,
            "works_attempted": 0,
            "soft_failed": True,
        }
