"""Provider-independent author identity resolution service."""

from __future__ import annotations

import logging
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.db.models import CanonicalAuthor, ProviderAuthorRecord
from app.services.author_resolution.candidate import (
    AuthorCandidate,
    candidate_from_provider_result,
    linked_openalex_id_from_orcid_metadata,
)
from app.services.author_resolution.repository import AuthorIdentityRepository
from app.integrations.orcid.normalize import normalize_orcid_id
from app.services.author_resolution.scoring import (
    DECISION_AUTO_MERGE,
    DECISION_POSSIBLE_DUPLICATE,
    score_candidate_pair,
)


logger = logging.getLogger(__name__)


def serialize_canonical_author(canonical: CanonicalAuthor) -> dict[str, Any]:
    aliases = sorted(
        {
            *(alias.alias for alias in canonical.aliases if alias.alias),
            *(
                record.display_name
                for record in canonical.provider_records
                if record.display_name
            ),
        }
    )
    aliases = [name for name in aliases if name != canonical.preferred_name]

    openalex_records = [
        record for record in canonical.provider_records if record.provider == "openalex"
    ]
    orcid_records = [
        record for record in canonical.provider_records if record.provider == "orcid"
    ]
    other_records = [
        record
        for record in canonical.provider_records
        if record.provider not in {"openalex", "orcid"}
    ]

    institutions: list[dict[str, Any]] = []
    seen_inst: set[str] = set()

    def add_institution(*, institution_id: str | None, name: str | None, country_code: str | None) -> None:
        key = (institution_id or "") + "|" + (name or "").strip().lower()
        if not institution_id and not name:
            return
        if key in seen_inst:
            return
        seen_inst.add(key)
        institutions.append(
            {
                "id": institution_id,
                "name": name,
                "country_code": country_code,
            }
        )

    # Prefer paper/OpenAlex affiliations; ORCID employments fill gaps only.
    for record in (*openalex_records, *other_records, *orcid_records):
        for inst in record.institutions:
            add_institution(
                institution_id=inst.institution_id,
                name=inst.display_name,
                country_code=inst.country_code,
            )

    employments: list[dict[str, Any]] = []
    external_ids: list[dict[str, Any]] = []
    orcid_works: list[dict[str, Any]] = []
    seen_ext: set[str] = set()
    seen_doi: set[str] = set()
    for record in orcid_records:
        metadata = record.raw_metadata if isinstance(record.raw_metadata, dict) else {}
        for emp in metadata.get("employments") or []:
            if isinstance(emp, dict):
                employments.append(emp)
        for ext in metadata.get("external_ids") or []:
            if not isinstance(ext, dict):
                continue
            key = f"{ext.get('type')}|{ext.get('value')}"
            if key in seen_ext:
                continue
            seen_ext.add(key)
            external_ids.append(ext)
        for work in record.works:
            work_id = work.work_id
            if not work_id or work_id in seen_doi:
                continue
            seen_doi.add(work_id)
            orcid_works.append(
                {
                    "id": work_id,
                    "id_type": work.work_id_type,
                    "title": work.title,
                    "publication_year": work.publication_year,
                }
            )

    works_count = 0
    for record in canonical.provider_records:
        if record.works_count is not None:
            works_count = max(works_count, int(record.works_count))

    confidence = 1.0 if canonical.resolution_status == "merged" else 0.7
    if canonical.resolution_status == "unresolved":
        confidence = 0.5

    source = None
    if openalex_records:
        source = "openalex"
    elif orcid_records:
        source = "orcid"
    elif canonical.provider_records:
        source = canonical.provider_records[0].provider

    return {
        "id": str(canonical.id),
        "result_id": str(canonical.id),
        "result_type": "author",
        "display_name": canonical.preferred_name,
        "aliases": aliases,
        "institutions": institutions,
        "primary_institution": institutions[0] if institutions else None,
        "employments": employments,
        "external_ids": external_ids,
        "works": orcid_works,
        "works_count": works_count or None,
        "source_records": [
            {
                "provider": record.provider,
                "provider_author_id": record.provider_author_id,
            }
            for record in canonical.provider_records
        ],
        "identity_resolution": {
            "status": canonical.resolution_status,
            "confidence": confidence,
        },
        "source": source,
        "openalex_id": next(
            (
                record.provider_author_id
                for record in openalex_records
            ),
            None,
        ),
        "orcid": next(
            (record.orcid for record in canonical.provider_records if record.orcid),
            None,
        ),
    }


class AuthorResolutionService:
    def __init__(
        self,
        session: AsyncSession,
        *,
        auto_merge_threshold: int | None = None,
        possible_duplicate_threshold: int | None = None,
    ) -> None:
        settings = get_settings()
        self.repo = AuthorIdentityRepository(session)
        self.session = session
        self.auto_merge_threshold = (
            auto_merge_threshold
            if auto_merge_threshold is not None
            else settings.author_auto_merge_threshold
        )
        self.possible_duplicate_threshold = (
            possible_duplicate_threshold
            if possible_duplicate_threshold is not None
            else settings.author_possible_duplicate_threshold
        )

    async def _attach_linked_openalex_from_search(
        self,
        candidate: AuthorCandidate,
        canonical: CanonicalAuthor,
    ) -> CanonicalAuthor:
        """Persist a pre-linked OpenAlex provider record from ORCID search metadata."""
        if candidate.provider != "orcid":
            return canonical

        openalex_id = linked_openalex_id_from_orcid_metadata(
            orcid=candidate.orcid,
            raw_metadata=candidate.raw_metadata,
        )
        if not openalex_id:
            return canonical

        openalex_candidate = AuthorCandidate(
            provider="openalex",
            provider_author_id=openalex_id,
            display_name=candidate.display_name,
            aliases=list(candidate.aliases),
            institutions=list(candidate.institutions),
            works=list(candidate.works),
            topics=list(candidate.topics),
            orcid=candidate.orcid,
            works_count=candidate.works_count,
            raw_metadata=candidate.raw_metadata,
        )
        openalex_record = await self.repo.upsert_provider_record(openalex_candidate)
        if openalex_record.canonical_author_id:
            if openalex_record.canonical_author_id == canonical.id:
                refreshed = await self.repo.load_canonical(canonical.id)
                return refreshed or canonical
            linked_orcid = normalize_orcid_id(openalex_record.orcid)
            candidate_orcid = normalize_orcid_id(candidate.orcid)
            if linked_orcid and candidate_orcid and linked_orcid != candidate_orcid:
                return canonical
            return canonical

        await self.repo.attach_record_to_canonical(openalex_record, canonical)
        refreshed = await self.repo.load_canonical(canonical.id)
        return refreshed or canonical

    async def _complete_resolution(
        self,
        candidate: AuthorCandidate,
        canonical: CanonicalAuthor,
        *,
        created_new: bool,
    ) -> tuple[dict[str, Any], bool]:
        canonical = await self._attach_linked_openalex_from_search(candidate, canonical)
        return serialize_canonical_author(canonical), created_new

    async def resolve_candidate(
        self,
        candidate: AuthorCandidate,
    ) -> tuple[dict[str, Any], bool]:
        """
        Upsert provider record and resolve identity.

        Returns (canonical_payload, created_new_canonical).
        """
        record = await self.repo.upsert_provider_record(candidate)
        created_new = False

        if record.canonical_author_id:
            canonical = await self._maybe_merge_with_blockers(candidate, record)
            return await self._complete_resolution(candidate, canonical, created_new=False)

        blockers = await self.repo.find_blocking_candidates(
            candidate,
            exclude_record_id=record.id,
        )

        best_merge: ProviderAuthorRecord | None = None
        best_total = -1.0
        for other in blockers:
            score = score_candidate_pair(
                candidate,
                other,
                auto_merge_threshold=self.auto_merge_threshold,
                possible_duplicate_threshold=self.possible_duplicate_threshold,
            )
            await self.repo.add_match_evidence(
                record_a_id=record.id,
                record_b_id=other.id,
                total_score=score.total_score,
                name_score=score.name_score,
                institution_score=score.institution_score,
                work_overlap_score=score.work_overlap_score,
                coauthor_score=score.coauthor_score,
                decision=score.decision,
                reasoning=score.reasoning,
            )
            if (
                score.decision == DECISION_AUTO_MERGE
                and score.total_score > best_total
            ):
                best_merge = other
                best_total = score.total_score

        if best_merge is not None:
            if best_merge.canonical_author_id:
                canonical = await self.repo.load_canonical(best_merge.canonical_author_id)
            else:
                canonical = None

            if canonical is None:
                canonical = await self.repo.create_canonical_author(
                    preferred_name=best_merge.display_name,
                    normalized_name=best_merge.normalized_name,
                    surname=best_merge.surname,
                    first_initial=best_merge.first_initial,
                    resolution_status="merged",
                )
                await self.repo.attach_record_to_canonical(best_merge, canonical)
                created_new = True

            await self.repo.attach_record_to_canonical(
                record,
                canonical,
                alias=candidate.display_name,
                status="merged",
            )
            canonical = await self.repo.load_canonical(canonical.id)
            assert canonical is not None
            return await self._complete_resolution(candidate, canonical, created_new=created_new)

        status = "resolved" if candidate.provider in {"openalex", "orcid"} else "unresolved"
        canonical = await self.repo.create_canonical_author(
            preferred_name=candidate.display_name,
            normalized_name=candidate.normalized_name,
            surname=candidate.surname,
            first_initial=candidate.first_initial,
            resolution_status=status,
            aliases=candidate.aliases,
        )
        await self.repo.attach_record_to_canonical(record, canonical)
        canonical = await self.repo.load_canonical(canonical.id)
        assert canonical is not None
        return await self._complete_resolution(candidate, canonical, created_new=True)

    async def _maybe_merge_with_blockers(
        self,
        candidate: AuthorCandidate,
        record: ProviderAuthorRecord,
    ) -> CanonicalAuthor:
        assert record.canonical_author_id is not None
        canonical = await self.repo.load_canonical(record.canonical_author_id)
        assert canonical is not None

        await self.repo.attach_record_to_canonical(
            record,
            canonical,
            alias=candidate.display_name,
        )

        blockers = await self.repo.find_blocking_candidates(
            candidate,
            exclude_record_id=record.id,
        )
        for other in blockers:
            if not other.canonical_author_id:
                continue
            if other.canonical_author_id == canonical.id:
                continue
            score = score_candidate_pair(
                candidate,
                other,
                auto_merge_threshold=self.auto_merge_threshold,
                possible_duplicate_threshold=self.possible_duplicate_threshold,
            )
            await self.repo.add_match_evidence(
                record_a_id=record.id,
                record_b_id=other.id,
                total_score=score.total_score,
                name_score=score.name_score,
                institution_score=score.institution_score,
                work_overlap_score=score.work_overlap_score,
                coauthor_score=score.coauthor_score,
                decision=score.decision,
                reasoning=score.reasoning,
            )
            if score.decision != DECISION_AUTO_MERGE:
                continue
            other_canonical = await self.repo.load_canonical(other.canonical_author_id)
            if other_canonical is None:
                continue
            if canonical.created_at <= other_canonical.created_at:
                canonical = await self.repo.merge_canonicals(
                    canonical, other_canonical
                )
            else:
                canonical = await self.repo.merge_canonicals(
                    other_canonical, canonical
                )

        refreshed = await self.repo.load_canonical(canonical.id)
        assert refreshed is not None
        return refreshed


async def resolve_author_page(
    session: AsyncSession,
    provider_results: list[dict[str, Any]],
    *,
    known_canonical_ids: set[str] | None = None,
) -> dict[str, Any]:
    """
    Resolve a provider author page into insert/replace operations.

    A duplicate discovered on a later page updates the existing canonical author
    and does not create another list card.
    """
    service = AuthorResolutionService(session)
    known = set(known_canonical_ids or [])
    items: list[dict[str, Any]] = []
    updates: list[dict[str, Any]] = []
    results: list[dict[str, Any]] = []
    seen_page_ids: set[str] = set()

    for raw in provider_results:
        candidate = candidate_from_provider_result(raw)
        if candidate is None:
            continue

        try:
            author, _created = await service.resolve_candidate(candidate)
        except Exception:
            if candidate.provider == "orcid":
                logger.warning(
                    "orcid_resolution_failed provider_author_id=%s",
                    candidate.provider_author_id,
                )
                continue
            raise
        canonical_id = author["id"]

        if canonical_id in known or canonical_id in seen_page_ids:
            updates.append(
                {
                    "operation": "replace",
                    "canonical_author_id": canonical_id,
                    "author": author,
                }
            )
            continue

        seen_page_ids.add(canonical_id)
        known.add(canonical_id)
        items.append({"operation": "insert", "author": author})
        results.append(author)

    await session.commit()
    return {
        "items": items,
        "updates": updates,
        "results": results,
        "known_canonical_ids": sorted(known),
    }
