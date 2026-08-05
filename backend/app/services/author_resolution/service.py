"""Provider-independent author identity resolution service."""

from __future__ import annotations

from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.db.models import CanonicalAuthor, ProviderAuthorRecord
from app.services.author_resolution.candidate import (
    AuthorCandidate,
    candidate_from_provider_result,
)
from app.services.author_resolution.repository import AuthorIdentityRepository
from app.services.author_resolution.scoring import (
    DECISION_AUTO_MERGE,
    DECISION_POSSIBLE_DUPLICATE,
    score_candidate_pair,
)


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

    institutions: list[dict[str, Any]] = []
    seen_inst: set[str] = set()
    works_count = 0
    for record in canonical.provider_records:
        if record.works_count is not None:
            works_count = max(works_count, int(record.works_count))
        for inst in record.institutions:
            key = (inst.institution_id or "") + "|" + (inst.normalized_name or "")
            if key in seen_inst:
                continue
            seen_inst.add(key)
            institutions.append(
                {
                    "id": inst.institution_id,
                    "name": inst.display_name,
                    "country_code": inst.country_code,
                }
            )

    confidence = 1.0 if canonical.resolution_status == "merged" else 0.7
    if canonical.resolution_status == "unresolved":
        confidence = 0.5

    return {
        "id": str(canonical.id),
        "result_id": str(canonical.id),
        "result_type": "author",
        "display_name": canonical.preferred_name,
        "aliases": aliases,
        "institutions": institutions,
        "primary_institution": institutions[0] if institutions else None,
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
        "source": (
            canonical.provider_records[0].provider
            if canonical.provider_records
            else None
        ),
        "openalex_id": next(
            (
                record.provider_author_id
                for record in canonical.provider_records
                if record.provider == "openalex"
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
            return serialize_canonical_author(canonical), False

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
            return serialize_canonical_author(canonical), created_new

        status = "resolved" if candidate.provider == "openalex" else "unresolved"
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
        return serialize_canonical_author(canonical), True

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

        author, _created = await service.resolve_candidate(candidate)
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
