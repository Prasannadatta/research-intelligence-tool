"""Persistence helpers for author identity resolution."""

from __future__ import annotations

import uuid
from typing import Any, Sequence

from sqlalchemy import and_, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.db.models import (
    AuthorAlias,
    AuthorInstitution,
    AuthorMatchEvidence,
    AuthorWork,
    CanonicalAuthor,
    ProviderAuthorRecord,
)
from app.services.author_resolution.candidate import AuthorCandidate
from app.services.author_resolution.normalization import normalize_author_name
from app.services.author_resolution.scoring import expand_work_id_keys, normalize_work_id


class AuthorIdentityRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get_provider_record(
        self,
        provider: str,
        provider_author_id: str,
    ) -> ProviderAuthorRecord | None:
        stmt = (
            select(ProviderAuthorRecord)
            .where(
                ProviderAuthorRecord.provider == provider,
                ProviderAuthorRecord.provider_author_id == provider_author_id,
            )
            .options(
                selectinload(ProviderAuthorRecord.institutions),
                selectinload(ProviderAuthorRecord.works),
                selectinload(ProviderAuthorRecord.canonical_author).selectinload(
                    CanonicalAuthor.aliases
                ),
                selectinload(ProviderAuthorRecord.canonical_author).selectinload(
                    CanonicalAuthor.provider_records
                ),
            )
        )
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def get_provider_records_by_keys(
        self,
        keys: Sequence[tuple[str, str]],
    ) -> dict[tuple[str, str], ProviderAuthorRecord]:
        """Batch-load provider records keyed by (provider, provider_author_id)."""
        unique_keys = list(dict.fromkeys(
            (str(provider or "").strip().lower(), str(provider_author_id or "").strip())
            for provider, provider_author_id in keys
            if str(provider or "").strip() and str(provider_author_id or "").strip()
        ))
        if not unique_keys:
            return {}

        conditions = [
            and_(
                ProviderAuthorRecord.provider == provider,
                ProviderAuthorRecord.provider_author_id == provider_author_id,
            )
            for provider, provider_author_id in unique_keys
        ]
        stmt = (
            select(ProviderAuthorRecord)
            .where(or_(*conditions))
            .options(
                selectinload(ProviderAuthorRecord.canonical_author).selectinload(
                    CanonicalAuthor.aliases
                ),
                selectinload(ProviderAuthorRecord.canonical_author).selectinload(
                    CanonicalAuthor.provider_records
                ).selectinload(ProviderAuthorRecord.institutions),
                selectinload(ProviderAuthorRecord.canonical_author).selectinload(
                    CanonicalAuthor.provider_records
                ).selectinload(ProviderAuthorRecord.works),
            )
        )
        result = await self.session.execute(stmt)
        out: dict[tuple[str, str], ProviderAuthorRecord] = {}
        for record in result.scalars().all():
            key = (
                str(record.provider or "").strip().lower(),
                str(record.provider_author_id or "").strip(),
            )
            out[key] = record
        return out

    async def upsert_provider_record(
        self,
        candidate: AuthorCandidate,
    ) -> ProviderAuthorRecord:
        from sqlalchemy import delete

        existing = await self.get_provider_record(
            candidate.provider,
            candidate.provider_author_id,
        )
        if existing is None:
            existing = ProviderAuthorRecord(
                id=uuid.uuid4(),
                provider=candidate.provider,
                provider_author_id=candidate.provider_author_id,
                display_name=candidate.display_name,
                normalized_name=candidate.normalized_name,
                surname=candidate.surname,
                first_initial=candidate.first_initial,
                orcid=candidate.orcid,
                works_count=candidate.works_count,
                raw_metadata=candidate.raw_metadata,
            )
            self.session.add(existing)
            await self.session.flush()
        else:
            existing.display_name = candidate.display_name
            existing.normalized_name = candidate.normalized_name
            existing.surname = candidate.surname
            existing.first_initial = candidate.first_initial
            existing.orcid = candidate.orcid
            existing.works_count = candidate.works_count
            existing.raw_metadata = candidate.raw_metadata
            await self.session.execute(
                delete(AuthorInstitution).where(
                    AuthorInstitution.provider_author_record_id == existing.id
                )
            )
            await self.session.flush()

        for inst in candidate.institutions:
            self.session.add(
                AuthorInstitution(
                    id=uuid.uuid4(),
                    provider_author_record_id=existing.id,
                    institution_id=inst.id,
                    display_name=inst.name,
                    normalized_name=normalize_author_name(inst.name)
                    if inst.name
                    else None,
                    country_code=inst.country_code,
                )
            )

        existing_work_ids = {
            row[0]
            for row in (
                await self.session.execute(
                    select(AuthorWork.work_id).where(
                        AuthorWork.provider_author_record_id == existing.id
                    )
                )
            ).all()
        }
        for work in candidate.works:
            stored_id = normalize_work_id(work.id, id_type=work.id_type) or work.id
            if stored_id in existing_work_ids:
                continue
            existing_work_ids.add(stored_id)
            self.session.add(
                AuthorWork(
                    id=uuid.uuid4(),
                    provider_author_record_id=existing.id,
                    work_id=stored_id,
                    work_id_type=work.id_type or (
                        "doi" if str(stored_id).startswith("doi:") else None
                    ),
                    title=work.title,
                    publication_year=work.publication_year,
                )
            )

        await self.session.flush()
        refreshed = await self.get_provider_record(
            candidate.provider,
            candidate.provider_author_id,
        )
        assert refreshed is not None
        return refreshed

    async def find_blocking_candidates(
        self,
        candidate: AuthorCandidate,
        *,
        exclude_record_id: uuid.UUID | None = None,
        limit: int = 50,
    ) -> list[ProviderAuthorRecord]:
        clauses = []
        if candidate.normalized_name:
            clauses.append(
                ProviderAuthorRecord.normalized_name == candidate.normalized_name
            )
        if candidate.surname and candidate.first_initial:
            clauses.append(
                (ProviderAuthorRecord.surname == candidate.surname)
                & (ProviderAuthorRecord.first_initial == candidate.first_initial)
            )
        if candidate.orcid:
            clauses.append(ProviderAuthorRecord.orcid == candidate.orcid)

        work_ids: list[str] = []
        for work in candidate.works:
            work_ids.extend(expand_work_id_keys(work.id, id_type=work.id_type))
        work_ids = list({key for key in work_ids if key})
        if work_ids:
            work_subq = select(AuthorWork.provider_author_record_id).where(
                AuthorWork.work_id.in_(work_ids)
            )
            clauses.append(ProviderAuthorRecord.id.in_(work_subq))

        institution_ids = [
            inst.id for inst in candidate.institutions if inst.id
        ]
        if institution_ids and candidate.surname and candidate.first_initial:
            inst_subq = select(AuthorInstitution.provider_author_record_id).where(
                AuthorInstitution.institution_id.in_(institution_ids)
            )
            clauses.append(
                ProviderAuthorRecord.id.in_(inst_subq)
                & (ProviderAuthorRecord.surname == candidate.surname)
                & (ProviderAuthorRecord.first_initial == candidate.first_initial)
            )

        if not clauses:
            return []

        stmt = (
            select(ProviderAuthorRecord)
            .where(or_(*clauses))
            .options(
                selectinload(ProviderAuthorRecord.institutions),
                selectinload(ProviderAuthorRecord.works),
                selectinload(ProviderAuthorRecord.canonical_author).selectinload(
                    CanonicalAuthor.provider_records
                ),
                selectinload(ProviderAuthorRecord.canonical_author).selectinload(
                    CanonicalAuthor.aliases
                ),
            )
            .limit(limit)
        )
        if exclude_record_id is not None:
            stmt = stmt.where(ProviderAuthorRecord.id != exclude_record_id)

        result = await self.session.execute(stmt)
        return list(result.scalars().unique().all())

    async def create_canonical_author(
        self,
        *,
        preferred_name: str,
        normalized_name: str,
        surname: str | None,
        first_initial: str | None,
        resolution_status: str,
        aliases: Sequence[str] = (),
    ) -> CanonicalAuthor:
        author = CanonicalAuthor(
            id=uuid.uuid4(),
            preferred_name=preferred_name,
            normalized_name=normalized_name,
            surname=surname,
            first_initial=first_initial,
            resolution_status=resolution_status,
        )
        self.session.add(author)
        await self.session.flush()

        seen = {normalized_name}
        for alias in aliases:
            text = (alias or "").strip()
            if not text:
                continue
            norm = normalize_author_name(text)
            if not norm or norm in seen:
                continue
            seen.add(norm)
            self.session.add(
                AuthorAlias(
                    id=uuid.uuid4(),
                    canonical_author_id=author.id,
                    alias=text,
                    normalized_alias=norm,
                )
            )
        await self.session.flush()
        return author

    async def attach_record_to_canonical(
        self,
        record: ProviderAuthorRecord,
        canonical: CanonicalAuthor,
        *,
        alias: str | None = None,
        status: str | None = None,
    ) -> None:
        record.canonical_author_id = canonical.id
        if status:
            canonical.resolution_status = status
        if alias:
            norm = normalize_author_name(alias)
            existing = {
                a.normalized_alias for a in (canonical.aliases or [])
            }
            if norm and norm not in existing and norm != canonical.normalized_name:
                self.session.add(
                    AuthorAlias(
                        id=uuid.uuid4(),
                        canonical_author_id=canonical.id,
                        alias=alias,
                        normalized_alias=norm,
                    )
                )
        await self.session.flush()

    async def merge_canonicals(
        self,
        keep: CanonicalAuthor,
        discard: CanonicalAuthor,
    ) -> CanonicalAuthor:
        if keep.id == discard.id:
            return keep

        # Transfer via relationship collections so cascade="all, delete-orphan"
        # does not delete provider records that were only FK-reassigned.
        for record in list(discard.provider_records):
            discard.provider_records.remove(record)
            record.canonical_author_id = keep.id
            keep.provider_records.append(record)

        keep_aliases = {a.normalized_alias for a in keep.aliases}
        keep_aliases.add(keep.normalized_name)
        for alias in list(discard.aliases):
            if alias.normalized_alias in keep_aliases:
                discard.aliases.remove(alias)
                await self.session.delete(alias)
                continue
            discard.aliases.remove(alias)
            alias.canonical_author_id = keep.id
            keep.aliases.append(alias)
            keep_aliases.add(alias.normalized_alias)

        # Preserve discard preferred name as alias when distinct.
        discard_norm = discard.normalized_name
        if discard_norm and discard_norm not in keep_aliases:
            self.session.add(
                AuthorAlias(
                    id=uuid.uuid4(),
                    canonical_author_id=keep.id,
                    alias=discard.preferred_name,
                    normalized_alias=discard_norm,
                )
            )

        keep.resolution_status = "merged"
        await self.session.delete(discard)
        await self.session.flush()
        return keep

    async def add_match_evidence(
        self,
        *,
        record_a_id: uuid.UUID,
        record_b_id: uuid.UUID,
        total_score: float,
        name_score: float,
        institution_score: float,
        work_overlap_score: float,
        coauthor_score: float,
        decision: str,
        reasoning: dict[str, Any] | None,
    ) -> AuthorMatchEvidence:
        a_id, b_id = sorted([record_a_id, record_b_id], key=str)
        evidence = AuthorMatchEvidence(
            id=uuid.uuid4(),
            record_a_id=a_id,
            record_b_id=b_id,
            total_score=total_score,
            name_score=name_score,
            institution_score=institution_score,
            work_overlap_score=work_overlap_score,
            coauthor_score=coauthor_score,
            decision=decision,
            reasoning=reasoning,
        )
        self.session.add(evidence)
        await self.session.flush()
        return evidence

    async def load_canonical(
        self,
        canonical_id: uuid.UUID,
    ) -> CanonicalAuthor | None:
        stmt = (
            select(CanonicalAuthor)
            .where(CanonicalAuthor.id == canonical_id)
            .options(
                selectinload(CanonicalAuthor.aliases),
                selectinload(CanonicalAuthor.provider_records).selectinload(
                    ProviderAuthorRecord.institutions
                ),
                selectinload(CanonicalAuthor.provider_records).selectinload(
                    ProviderAuthorRecord.works
                ),
            )
            .execution_options(populate_existing=True)
        )
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()
