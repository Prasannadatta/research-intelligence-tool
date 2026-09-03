"""Manual stale-data refresh orchestration."""

from __future__ import annotations

import asyncio
import logging
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.config import get_settings
from app.db.models import (
    CanonicalAuthor,
    CanonicalWork,
    DataUpdateJob,
    ProviderAuthorRecord,
    ProviderWorkRecord,
)
from app.db.session import SessionLocal
from app.integrations.openalex.author_works import extract_grants_from_openalex_work
from app.integrations.openalex.client import (
    OpenAlexApiError,
    _openalex_get,
    _require_api_key,
    _short_openalex_id,
    fetch_openalex_author_payload,
    normalize_openalex_author,
)
from app.integrations.openalex.unified_search import OPENALEX_WORKS_URL, normalize_search_work
from app.schemas.data_updater import DataUpdateRequest
from app.services.analysis.author_work_sync import AuthorWorkSyncService
from app.services.authors.summary import (
    _load_profile_bundle,
    _upsert_profile_from_openalex,
)
from app.services.data_updater.repository import DataUpdaterRepository
from app.services.work_persistence.candidate import candidate_from_provider_result
from app.services.work_persistence.repository import WorkPersistenceRepository

logger = logging.getLogger(__name__)


class DataUpdaterError(Exception):
    def __init__(self, message: str, status_code: int = 400):
        super().__init__(message)
        self.status_code = status_code


@dataclass(frozen=True)
class DatasetDefinition:
    key: str
    label: str
    description: str
    ttl_setting: str | None
    refreshable_fields: tuple[str, ...]


DATASETS: tuple[DatasetDefinition, ...] = (
    DatasetDefinition(
        key="authors",
        label="Authors",
        description="Canonical author names, provider author records, works/citation counts, ORCID, topics.",
        ttl_setting="data_updater_author_profile_ttl_seconds",
        refreshable_fields=("preferred_name", "works_count", "citation_count", "h_index", "orcid", "topics", "provider raw_metadata"),
    ),
    DatasetDefinition(
        key="author_affiliations",
        label="Author affiliations",
        description="Current and historical author affiliation rows from provider author metadata.",
        ttl_setting="data_updater_affiliation_ttl_seconds",
        refreshable_fields=("institution_name", "institution_id", "department", "country_code", "valid years", "current flag"),
    ),
    DatasetDefinition(
        key="institutions",
        label="Universities / institutions",
        description="Institution names and identifiers embedded in author affiliations and publication authorships.",
        ttl_setting="data_updater_affiliation_ttl_seconds",
        refreshable_fields=("institution_name", "institution_id", "department", "country_code"),
    ),
    DatasetDefinition(
        key="author_publications",
        label="Author publication lists",
        description="Author-to-publication coverage and provider work links for selected canonical authors.",
        ttl_setting="data_updater_author_publications_ttl_seconds",
        refreshable_fields=("author_works", "work_authorships", "provider_work_records"),
    ),
    DatasetDefinition(
        key="publications",
        label="Publications",
        description="Canonical work rows and provider work snapshots.",
        ttl_setting="data_updater_publication_metadata_ttl_seconds",
        refreshable_fields=("title", "doi", "arxiv_id", "pmid", "publication_year", "authors", "venue"),
    ),
    DatasetDefinition(
        key="publication_metadata",
        label="Publication metadata",
        description="Provider work metadata, authorships, venues, URLs, DOI/arXiv/PMID fields.",
        ttl_setting="data_updater_publication_metadata_ttl_seconds",
        refreshable_fields=("provider raw_metadata", "authorships", "source metadata", "identifiers"),
    ),
    DatasetDefinition(
        key="citation_counts",
        label="Citation counts",
        description="Citation metrics stored on author profiles and OpenAlex work snapshots.",
        ttl_setting="data_updater_citation_counts_ttl_seconds",
        refreshable_fields=("cited_by_count", "citation_count", "h_index"),
    ),
    DatasetDefinition(
        key="grant_funding",
        label="Grant / funding information",
        description="Structured funding award links and grant match metadata from provider work snapshots.",
        ttl_setting="data_updater_grant_info_ttl_seconds",
        refreshable_fields=("awards", "grant_number", "funder_name", "verified", "match_type"),
    ),
    DatasetDefinition(
        key="provider_search_cache",
        label="Provider search cache",
        description="Expired cached provider responses.",
        ttl_setting=None,
        refreshable_fields=("expires_at", "response"),
    ),
    DatasetDefinition(
        key="search_sessions",
        label="Search sessions",
        description="Expired persisted search sessions and result lists.",
        ttl_setting=None,
        refreshable_fields=("expires_at", "results"),
    ),
)

DATASET_BY_KEY = {definition.key: definition for definition in DATASETS}


def _serialize_job(job: DataUpdateJob) -> dict[str, Any]:
    return {
        "id": str(job.id),
        "mode": job.mode,
        "dataset": job.dataset,
        "status": job.status,
        "current_dataset": job.current_dataset,
        "total_records": job.total_records,
        "processed_records": job.processed_records,
        "updated_count": job.updated_count,
        "unchanged_count": job.unchanged_count,
        "retrying_count": job.retrying_count,
        "failed_count": job.failed_count,
        "requested_record_ids": job.requested_record_ids,
        "metadata": job.metadata_,
        "error": job.error,
        "created_at": job.created_at,
        "updated_at": job.updated_at,
        "started_at": job.started_at,
        "completed_at": job.completed_at,
    }


def _serialize_record(record) -> dict[str, Any]:
    return {
        "id": str(record.id),
        "job_id": str(record.job_id),
        "dataset": record.dataset,
        "record_id": record.record_id,
        "source": record.source,
        "status": record.status,
        "message": record.message,
        "retry_count": record.retry_count,
        "created_at": record.created_at,
        "updated_at": record.updated_at,
    }


def _normalize_openalex_work_payload(raw: dict[str, Any]) -> dict[str, Any] | None:
    row = normalize_search_work(raw)
    if row is None:
        return None
    grants = extract_grants_from_openalex_work(raw)
    row["grants"] = grants
    if row.get("cited_by_count") is not None:
        row["citation_count"] = row["cited_by_count"]
    if row.get("primary_source") and not row.get("journal"):
        row["journal"] = row["primary_source"]
    return row


class DataUpdaterService:
    def __init__(self, session: AsyncSession):
        self.session = session
        self.repo = DataUpdaterRepository(session)
        self.settings = get_settings()

    async def categories(self) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        for definition in DATASETS:
            ttl = self._ttl_for(definition)
            try:
                total = await self.repo.count_refresh_targets(definition.key)
                stale = await self.repo.count_stale_targets(definition.key, ttl)
            except Exception:
                logger.exception("Failed to count refresh targets for %s", definition.key)
                total = 0
                stale = 0
            rows.append(
                {
                    "key": definition.key,
                    "label": definition.label,
                    "description": definition.description,
                    "total_records": total,
                    "stale_records": stale,
                    "refresh_interval_seconds": ttl,
                    "refreshable_fields": list(definition.refreshable_fields),
                }
            )
        return rows

    async def search_targets(self, query: str, *, limit: int = 8) -> list[dict[str, Any]]:
        return await self.repo.search_user_refresh_targets(query, limit=limit)

    async def saved_search_options(self) -> list[dict[str, Any]]:
        rows = await self.repo.list_saved_search_options()
        return [
            {
                "id": str(row.id),
                "name": row.display_name,
                "search_type": row.search_type,
                "updated_at": row.updated_at,
            }
            for row in rows
        ]

    async def start_job(self, request: DataUpdateRequest) -> dict[str, Any]:
        dataset = self._validate_request(request)
        record_ids = self._record_ids_for_request(request)
        job = await self.repo.create_job(
            mode=request.mode,
            dataset=dataset,
            record_ids=record_ids,
            metadata={
                "stale_only": request.stale_only,
            },
        )
        await self.session.commit()
        if request.run_inline:
            await self.run_job(str(job.id))
            refreshed = await self.repo.get_job(job.id)
            assert refreshed is not None
            return _serialize_job(refreshed)
        asyncio.create_task(run_data_update_job(str(job.id)))
        return _serialize_job(job)

    async def start_entity_job(
        self,
        *,
        entity_type: str,
        entity_id: str,
        stale_only: bool = False,
    ) -> dict[str, Any]:
        plan, title = await self._target_plan_for_entity(entity_type, entity_id)
        return await self._create_user_job(
            mode="selected",
            title=f"Updating {title}",
            target_plan=plan,
            stale_only=stale_only,
        )

    async def start_saved_search_job(
        self,
        *,
        saved_search_id: str,
        stale_only: bool = True,
    ) -> dict[str, Any]:
        saved_search = await self.repo.get_saved_search(
            saved_search_id
        )
        if saved_search is None:
            raise DataUpdaterError("Saved search not found.", 404)
        plan = await self._target_plan_for_saved_search(saved_search)
        return await self._create_user_job(
            mode="saved_search",
            title=f"Updating {saved_search.display_name}",
            target_plan=plan,
            stale_only=stale_only,
            extra_metadata={
                "saved_search_id": str(saved_search.id),
            },
        )

    async def start_all_saved_searches_job(self, *, stale_only: bool = True) -> dict[str, Any]:
        saved_searches = await self.repo.list_saved_searches()
        combined: dict[str, set[str]] = {}
        names: list[str] = []
        for saved_search in saved_searches:
            try:
                plan = await self._target_plan_for_saved_search(saved_search)
            except DataUpdaterError:
                continue
            names.append(saved_search.display_name)
            for dataset, record_ids in plan.items():
                combined.setdefault(dataset, set()).update(record_ids)
        if not combined:
            raise DataUpdaterError("No refreshable saved-search data was found.", 404)
        return await self._create_user_job(
            mode="all_saved_searches",
            title="Updating all saved searches",
            target_plan={dataset: sorted(record_ids) for dataset, record_ids in combined.items()},
            stale_only=stale_only,
            extra_metadata={
                "saved_search_count": len(names),
            },
        )

    async def pause_job(self, job_id: str) -> dict[str, Any]:
        job = await self.repo.get_job(job_id)
        if job is None:
            raise DataUpdaterError("Data update job not found.", 404)
        if job.status in {"queued", "running"}:
            await self.repo.request_job_pause(job)
            await self.session.commit()
        elif job.status == "pause_requested":
            pass
        elif job.status != "paused":
            raise DataUpdaterError("This update job cannot be paused.", 409)
        return await self.get_job(str(job.id), include_records=False)

    async def resume_job(self, job_id: str) -> dict[str, Any]:
        job = await self.repo.get_job(job_id)
        if job is None:
            raise DataUpdaterError("Data update job not found.", 404)
        if job.status != "paused":
            raise DataUpdaterError("Only paused update jobs can be resumed.", 409)
        job.status = "queued"
        job.completed_at = None
        await self.session.commit()
        asyncio.create_task(run_data_update_job(str(job.id)))
        return await self.get_job(str(job.id), include_records=False)

    async def cancel_job(self, job_id: str) -> dict[str, Any]:
        job = await self.repo.get_job(job_id)
        if job is None:
            raise DataUpdaterError("Data update job not found.", 404)
        if job.status in {"queued", "running", "pause_requested"}:
            await self.repo.request_job_cancel(job)
            await self.session.commit()
        elif job.status == "paused":
            await self.repo.mark_job_cancelled(job)
            await self.session.commit()
        elif job.status == "cancel_requested":
            pass
        elif job.status != "cancelled":
            raise DataUpdaterError("This update job cannot be cancelled.", 409)
        return await self.get_job(str(job.id), include_records=False)

    async def get_job(self, job_id: str, *, include_records: bool = True) -> dict[str, Any]:
        job = await self.repo.get_job(job_id)
        if job is None:
            raise DataUpdaterError("Data update job not found.", 404)
        payload = _serialize_job(job)
        if include_records:
            records = await self.repo.list_job_records(job.id)
            payload["records"] = [_serialize_record(record) for record in records]
        return payload

    async def _create_user_job(
        self,
        *,
        mode: str,
        title: str,
        target_plan: dict[str, list[str]],
        stale_only: bool,
        extra_metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        cleaned_plan = {
            dataset: sorted({str(record_id) for record_id in record_ids if record_id})
            for dataset, record_ids in target_plan.items()
            if dataset in DATASET_BY_KEY and record_ids
        }
        if not cleaned_plan:
            raise DataUpdaterError("No refreshable records were found.", 404)
        metadata: dict[str, Any] = {
            "stale_only": stale_only,
            "title": title,
            "datasets": list(cleaned_plan),
            "record_ids_by_dataset": cleaned_plan,
        }
        if extra_metadata:
            metadata.update(extra_metadata)
        job = await self.repo.create_job(
            mode=mode,
            dataset=None,
            record_ids=None,
            metadata=metadata,
        )
        await self.session.commit()
        asyncio.create_task(run_data_update_job(str(job.id)))
        return _serialize_job(job)

    async def _target_plan_for_entity(self, entity_type: str, entity_id: str) -> tuple[dict[str, list[str]], str]:
        if entity_type == "author":
            try:
                author_id = str(uuid.UUID(str(entity_id)))
            except ValueError as exc:
                raise DataUpdaterError("Author not found.", 404) from exc
            author = await self.session.get(CanonicalAuthor, uuid.UUID(author_id))
            if author is None:
                raise DataUpdaterError("Author not found.", 404)
            work_ids = await self.repo.publication_ids_for_authors([author_id])
            return self._author_target_plan([author_id], work_ids), author.preferred_name

        if entity_type == "publication":
            try:
                work_id = str(uuid.UUID(str(entity_id)))
            except ValueError as exc:
                raise DataUpdaterError("Publication not found.", 404) from exc
            work = await self.session.get(CanonicalWork, uuid.UUID(work_id))
            if work is None:
                raise DataUpdaterError("Publication not found.", 404)
            return self._publication_target_plan([work_id]), work.title

        if entity_type == "institution":
            author_ids = await self.repo.author_ids_for_institution(entity_id)
            if not author_ids:
                raise DataUpdaterError("Institution not found.", 404)
            work_ids = await self.repo.publication_ids_for_authors(author_ids)
            return self._author_target_plan(author_ids, work_ids), entity_id

        raise DataUpdaterError("Unsupported update target.", 422)

    async def _target_plan_for_saved_search(self, saved_search) -> dict[str, list[str]]:
        payload = saved_search.payload or {}
        if saved_search.search_type == "authors":
            authors = payload.get("authors") if isinstance(payload.get("authors"), list) else []
            all_author_ids = [
                str(author.get("canonical_author_id"))
                for author in authors
                if isinstance(author, dict) and author.get("canonical_author_id")
            ]
            active_ids = payload.get("active_author_ids") or all_author_ids
            author_ids = [str(author_id) for author_id in active_ids if str(author_id) in set(all_author_ids)]
            work_ids = await self.repo.publication_ids_for_authors(author_ids)
            return self._author_target_plan(author_ids, work_ids)

        if saved_search.search_type == "grant":
            work_ids = await self.repo.publication_ids_for_grant(str(payload.get("grant_number") or ""))
            return self._publication_target_plan(work_ids)

        raise DataUpdaterError("Unsupported saved search type.", 422)

    def _author_target_plan(self, author_ids: list[str], work_ids: list[str]) -> dict[str, list[str]]:
        plan = {
            "authors": author_ids,
            "author_affiliations": author_ids,
            "institutions": author_ids,
            "author_publications": author_ids,
        }
        if work_ids:
            plan.update(self._publication_target_plan(work_ids))
        return plan

    def _publication_target_plan(self, work_ids: list[str]) -> dict[str, list[str]]:
        return {
            "publications": work_ids,
            "publication_metadata": work_ids,
            "citation_counts": work_ids,
            "grant_funding": work_ids,
        }

    async def run_job(self, job_id: str) -> None:
        job = await self.repo.get_job(job_id)
        if job is None:
            raise DataUpdaterError("Data update job not found.", 404)
        try:
            if await self._stop_if_requested(job):
                return
            datasets = self._datasets_for_job(job)
            targets_by_dataset: dict[str, list[dict[str, Any]]] = {}
            completed_keys = await self.repo.completed_record_keys(job.id)
            remaining = 0
            for dataset in datasets:
                definition = DATASET_BY_KEY[dataset]
                targets = await self.repo.list_refresh_targets(
                    dataset,
                    ttl_seconds=self._ttl_for(definition),
                    record_ids=self._record_ids_for_dataset(job, dataset),
                    stale_only=bool((job.metadata_ or {}).get("stale_only", True)),
                )
                targets = [
                    target
                    for target in targets
                    if (dataset, str(target["record_id"])) not in completed_keys
                ]
                targets_by_dataset[dataset] = targets
                remaining += len(targets)
            total = max(job.total_records or 0, job.processed_records + remaining)
            await self.repo.mark_job_started(job, total=total)
            await self.session.commit()

            for dataset in datasets:
                if await self._stop_if_requested(job):
                    return
                job.current_dataset = dataset
                await self.session.commit()
                targets = targets_by_dataset[dataset]
                if not targets:
                    continue
                for target in targets:
                    if await self._stop_if_requested(job):
                        return
                    await self._process_target(job, dataset, target)
                    await self.session.commit()

            if await self._stop_if_requested(job):
                return
            status = "succeeded" if job.failed_count == 0 else "completed_with_errors"
            await self.repo.mark_job_completed(job, status=status)
            await self.session.commit()
        except Exception as exc:
            logger.exception("Data update job failed job_id=%s", job_id)
            await self.session.rollback()
            job = await self.repo.get_job(job_id)
            if job is not None:
                await self.repo.mark_job_failed(job, str(exc))
                await self.session.commit()

    async def _stop_if_requested(self, job: DataUpdateJob) -> bool:
        await self.session.refresh(job)
        if job.status == "pause_requested":
            await self.repo.mark_job_paused(job)
            await self.session.commit()
            return True
        if job.status == "cancel_requested":
            await self.repo.mark_job_cancelled(job)
            await self.session.commit()
            return True
        return job.status in {"paused", "cancelled"}

    def _ttl_for(self, definition: DatasetDefinition) -> int | None:
        if definition.ttl_setting is None:
            return 0
        return int(getattr(self.settings, definition.ttl_setting))

    def _validate_request(self, request: DataUpdateRequest) -> str | None:
        if request.mode in {"record", "selected", "dataset"}:
            dataset = request.dataset
            if not dataset or dataset not in DATASET_BY_KEY:
                raise DataUpdaterError("A valid dataset is required.", 422)
            if request.mode == "record" and not request.record_id:
                raise DataUpdaterError("record_id is required for single-record refresh.", 422)
            if request.mode == "selected" and not request.record_ids:
                raise DataUpdaterError("record_ids are required for selected-record refresh.", 422)
            return dataset
        return None

    def _record_ids_for_request(self, request: DataUpdateRequest) -> list[str] | None:
        if request.mode == "record":
            return [request.record_id] if request.record_id else []
        if request.mode == "selected":
            return request.record_ids
        return None

    def _record_ids_for_dataset(self, job: DataUpdateJob, dataset: str) -> list[str] | None:
        metadata = job.metadata_ or {}
        ids_by_dataset = metadata.get("record_ids_by_dataset")
        if isinstance(ids_by_dataset, dict):
            values = ids_by_dataset.get(dataset)
            if isinstance(values, list):
                return [str(value) for value in values if value]
        return job.requested_record_ids

    def _datasets_for_job(self, job: DataUpdateJob) -> list[str]:
        if job.mode == "all_stale":
            return [definition.key for definition in DATASETS]
        metadata = job.metadata_ or {}
        metadata_datasets = metadata.get("datasets")
        if isinstance(metadata_datasets, list) and metadata_datasets:
            return [str(dataset) for dataset in metadata_datasets if str(dataset) in DATASET_BY_KEY]
        if not job.dataset or job.dataset not in DATASET_BY_KEY:
            raise DataUpdaterError("A valid dataset is required.", 422)
        return [job.dataset]

    async def _process_target(
        self,
        job: DataUpdateJob,
        dataset: str,
        target: dict[str, Any],
    ) -> None:
        record_id = target["record_id"]
        source = target.get("source")
        try:
            if dataset in {"authors", "author_affiliations", "institutions"}:
                status, message = await self._refresh_author(record_id)
            elif dataset == "author_publications":
                status, message = await self._refresh_author_publications(record_id)
            elif dataset in {"publications", "publication_metadata", "citation_counts", "grant_funding"}:
                status, message = await self._refresh_publication(record_id)
            elif dataset == "provider_search_cache":
                deleted = await self.repo.delete_expired_cache()
                status, message = ("updated" if deleted else "unchanged", f"Deleted {deleted} expired cache rows.")
            elif dataset == "search_sessions":
                deleted = await self.repo.delete_expired_sessions()
                status, message = ("updated" if deleted else "unchanged", f"Deleted {deleted} expired sessions.")
            else:
                status, message = "unchanged", "No refresh operation is available for this dataset."
            await self.repo.upsert_subject_state(
                dataset=dataset,
                record_id=record_id,
                source=source,
                status=status,
                error=None,
            )
            await self.repo.add_record_result(
                job=job,
                dataset=dataset,
                record_id=record_id,
                source=source,
                status=status,
                message=message,
            )
        except Exception as exc:
            logger.warning(
                "data_update_record_failed job_id=%s dataset=%s record_id=%s error=%s",
                job.id,
                dataset,
                record_id,
                exc,
            )
            await self.repo.upsert_subject_state(
                dataset=dataset,
                record_id=record_id,
                source=source,
                status="failed",
                error=str(exc),
                retry_count=1,
            )
            await self.repo.add_record_result(
                job=job,
                dataset=dataset,
                record_id=record_id,
                source=source,
                status="failed",
                message=str(exc),
                retry_count=1,
            )

    async def _refresh_author(self, record_id: str) -> tuple[str, str]:
        try:
            canonical_id = uuid.UUID(str(record_id))
        except ValueError as exc:
            raise DataUpdaterError("Invalid canonical author ID.", 422) from exc
        canonical, profile, institutions = await _load_profile_bundle(self.session, canonical_id)
        if canonical is None:
            raise DataUpdaterError("Author not found.", 404)
        openalex_record = next(
            (record for record in canonical.provider_records if record.provider == "openalex"),
            None,
        )
        if openalex_record is None:
            return "unchanged", "No OpenAlex provider author record is linked."
        raw_openalex = await fetch_openalex_author_payload(openalex_record.provider_author_id)
        openalex_payload = normalize_openalex_author(raw_openalex)
        if not openalex_payload or not openalex_payload.get("display_name"):
            raise DataUpdaterError("OpenAlex returned incomplete author metadata.", 502)
        before = {
            "name": canonical.preferred_name,
            "works_count": openalex_record.works_count,
            "raw": openalex_record.raw_metadata,
            "profile_enriched_at": profile.enriched_at.isoformat() if profile and profile.enriched_at else None,
            "institutions": len(institutions),
        }
        canonical.preferred_name = openalex_payload["display_name"]
        openalex_record.display_name = openalex_payload["display_name"]
        openalex_record.works_count = openalex_payload.get("works_count") or openalex_record.works_count
        openalex_record.raw_metadata = raw_openalex
        await _upsert_profile_from_openalex(
            self.session,
            canonical,
            profile,
            openalex_payload,
            raw_openalex,
        )
        await self.session.flush()
        _, refreshed_profile, refreshed_institutions = await _load_profile_bundle(
            self.session,
            canonical_id,
        )
        after = {
            "name": canonical.preferred_name,
            "works_count": openalex_record.works_count,
            "raw": openalex_record.raw_metadata,
            "profile_enriched_at": refreshed_profile.enriched_at.isoformat() if refreshed_profile and refreshed_profile.enriched_at else None,
            "institutions": len(refreshed_institutions),
        }
        return ("updated" if before != after else "unchanged", "Author metadata refreshed from OpenAlex.")

    async def _refresh_author_publications(self, record_id: str) -> tuple[str, str]:
        canonical_id = uuid.UUID(str(record_id))
        canonical = (
            await self.session.execute(
                select(CanonicalAuthor)
                .where(CanonicalAuthor.id == canonical_id)
                .options(selectinload(CanonicalAuthor.provider_records))
            )
        ).scalar_one_or_none()
        if canonical is None:
            raise DataUpdaterError("Author not found.", 404)
        before_stats = await AuthorWorkSyncService(self.session).synchronize_selected_authors(
            [{"canonical_author_id": str(canonical.id)}],
        )
        if not before_stats:
            return "unchanged", "No refreshable provider author records are linked."
        changed = any(
            stat.get("new_works", 0) > 0
            or stat.get("existing_links_repaired", 0) > 0
            or stat.get("status") not in {"complete", "fresh", "success"}
            for stat in before_stats
        )
        return ("updated" if changed else "unchanged", "Author publication coverage synchronized.")

    async def _refresh_publication(self, record_id: str) -> tuple[str, str]:
        canonical_id = uuid.UUID(str(record_id))
        work = (
            await self.session.execute(
                select(CanonicalWork)
                .where(CanonicalWork.id == canonical_id)
                .options(selectinload(CanonicalWork.provider_records))
            )
        ).scalar_one_or_none()
        if work is None:
            raise DataUpdaterError("Publication not found.", 404)
        openalex_record = next(
            (record for record in work.provider_records if record.provider == "openalex"),
            None,
        )
        if openalex_record is None:
            return "unchanged", "No OpenAlex provider work record is linked."
        provider_work_id = _short_openalex_id(openalex_record.provider_work_id)
        if not provider_work_id:
            raise DataUpdaterError("Invalid OpenAlex work ID.", 422)
        api_key = _require_api_key()
        response = await _openalex_get(
            f"{OPENALEX_WORKS_URL}/{provider_work_id}",
            params={"api_key": api_key},
        )
        if response.status_code == 404:
            raise DataUpdaterError("Publication not found in OpenAlex.", 404)
        if response.status_code >= 400:
            raise OpenAlexApiError("OpenAlex rejected the publication refresh request.")
        raw = response.json()
        if not isinstance(raw, dict):
            raise DataUpdaterError("OpenAlex returned invalid publication metadata.", 502)
        normalized = _normalize_openalex_work_payload(raw)
        if normalized is None:
            raise DataUpdaterError("OpenAlex returned incomplete publication metadata.", 502)
        candidate = candidate_from_provider_result(normalized, provider="openalex")
        if candidate is None:
            raise DataUpdaterError("Publication metadata failed validation.", 502)
        before = {
            "title": work.title,
            "year": work.publication_year,
            "doi": work.doi,
            "raw": openalex_record.raw_metadata,
        }
        repo = WorkPersistenceRepository(self.session)
        repo.enrich_canonical_work(work, candidate)
        openalex_record.raw_metadata = candidate.raw_metadata
        openalex_record.retrieved_at = datetime.now(timezone.utc)
        await repo.replace_work_authorships(
            canonical_work_id=work.id,
            provider="openalex",
            provider_work_id=candidate.provider_work_id,
            raw_metadata=candidate.raw_metadata,
        )
        for grant in normalized.get("grants") or []:
            award_id = grant.get("award_id")
            if not award_id:
                continue
            await repo.upsert_grant_match(
                canonical_work_id=work.id,
                provider="openalex",
                grant_number=award_id,
                normalized_grant_number=str(award_id).lower(),
                verified=bool(grant.get("verified")),
                match_type=grant.get("match_type") or "structured_award_relationship",
                raw_metadata=grant,
            )
        await self.session.flush()
        after = {
            "title": work.title,
            "year": work.publication_year,
            "doi": work.doi,
            "raw": openalex_record.raw_metadata,
        }
        return ("updated" if before != after else "unchanged", "Publication metadata refreshed from OpenAlex.")


async def run_data_update_job(job_id: str) -> None:
    async with SessionLocal() as session:
        await DataUpdaterService(session).run_job(job_id)
