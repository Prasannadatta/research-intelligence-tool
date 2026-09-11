"""Persistence helpers for canonical works, sessions, cache, and grants."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.db.models import (
    AuthorWork,
    CanonicalWork,
    ProviderAuthorRecord,
    ProviderSearchCache,
    ProviderWorkRecord,
    SearchSession,
    SearchSessionResult,
    WorkAuthorship,
    WorkGrantMatch,
)
from app.services.work_persistence.candidate import WorkCandidate
from app.services.work_persistence.affiliations import normalize_affiliation_payload


def _canonical_provider_author_id(provider: str, provider_author_id: Any) -> str | None:
    text = str(provider_author_id or "").strip()
    if not text:
        return None
    if provider == "openalex":
        text = text.rstrip("/").split("/")[-1]
    return text or None


def _authorships_from_raw_metadata(
    raw_metadata: dict[str, Any] | None,
    *,
    provider: str,
) -> list[dict[str, Any]]:
    if not isinstance(raw_metadata, dict):
        return []
    authors = raw_metadata.get("authors")
    if not isinstance(authors, list):
        return []
    rows: list[dict[str, Any]] = []
    for index, author in enumerate(authors):
        if isinstance(author, str):
            name = " ".join(author.split()).strip()
            if not name:
                continue
            rows.append(
                {
                    "provider": provider,
                    "provider_author_id": None,
                    "display_name": name,
                    "author_position": index,
                    "orcid": None,
                    "institutions": [],
                    "institution_ids": [],
                    "countries": [],
                    "raw_metadata": {"name": name},
                }
            )
            continue
        if not isinstance(author, dict):
            continue
        affiliation = normalize_affiliation_payload(author)
        name = " ".join(
            str(
                author.get("display_name")
                or author.get("name")
                or author.get("raw_author_name")
                or ""
            ).split()
        ).strip()
        provider_author_id = (
            str(author.get("id") or author.get("openalex_id") or "").strip() or None
        )
        orcid = str(author.get("orcid") or "").strip() or None
        provider_ids = author.get("provider_ids")
        if isinstance(provider_ids, dict):
            openalex_ids = provider_ids.get("openalex") or []
            if not provider_author_id and openalex_ids:
                provider_author_id = str(openalex_ids[0]).strip() or None
            orcids = provider_ids.get("orcid") or []
            if not orcid and orcids:
                orcid = str(orcids[0]).strip() or None
        institutions = affiliation.institutions
        institution_ids = affiliation.institution_ids
        countries = affiliation.countries
        raw_author_metadata = dict(author)
        if affiliation.department:
            raw_author_metadata["department"] = affiliation.department
        if affiliation.raw_affiliation_text:
            raw_author_metadata["raw_affiliation_text"] = affiliation.raw_affiliation_text
        raw_author_metadata["affiliation_source"] = affiliation.affiliation_source
        raw_author_metadata["affiliation_confidence"] = affiliation.affiliation_confidence
        position = author.get("author_position")
        try:
            author_position = int(position) if position is not None else index
        except (TypeError, ValueError):
            author_position = index
        if not name and not provider_author_id:
            continue
        rows.append(
            {
                "provider": provider,
                "provider_author_id": provider_author_id,
                "display_name": name or provider_author_id or "Unknown author",
                "author_position": author_position,
                "orcid": orcid,
                "institutions": institutions,
                "institution_ids": institution_ids,
                "countries": countries,
                "raw_metadata": raw_author_metadata,
            }
        )
    return rows


class WorkPersistenceRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get_provider_record(
        self,
        provider: str,
        provider_work_id: str,
    ) -> ProviderWorkRecord | None:
        stmt = (
            select(ProviderWorkRecord)
            .where(
                ProviderWorkRecord.provider == provider,
                ProviderWorkRecord.provider_work_id == provider_work_id,
            )
            .options(selectinload(ProviderWorkRecord.canonical_work))
        )
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def find_canonical_by_doi(self, doi: str) -> CanonicalWork | None:
        stmt = select(CanonicalWork).where(CanonicalWork.doi == doi)
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def find_canonical_by_arxiv_id(self, arxiv_id: str) -> CanonicalWork | None:
        stmt = select(CanonicalWork).where(CanonicalWork.arxiv_id == arxiv_id)
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def find_canonical_by_pmid(self, pmid: str) -> CanonicalWork | None:
        stmt = select(CanonicalWork).where(CanonicalWork.pmid == pmid)
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def find_canonical_by_title_author_strong_timing(
        self,
        *,
        normalized_title: str,
        publication_year: int | None,
        publication_month: int | None,
        normalized_first_author: str | None,
    ) -> CanonicalWork | None:
        """Fallback merge only when title + first author + year + month all agree.

        Same title + year alone is not enough. If month precision is missing on
        either side, prefer keeping possible duplicates over incorrect merges.
        """
        if (
            not normalized_title
            or publication_year is None
            or publication_month is None
            or not (1 <= int(publication_month) <= 12)
            or not normalized_first_author
        ):
            return None

        stmt = select(CanonicalWork).where(
            CanonicalWork.normalized_title == normalized_title,
            CanonicalWork.publication_year == publication_year,
            CanonicalWork.normalized_first_author == normalized_first_author,
        )
        candidates = list((await self.session.execute(stmt)).scalars().all())
        if not candidates:
            return None

        from app.services.work_persistence.normalization import extract_publication_timing

        for work in candidates:
            provider_rows = (
                await self.session.execute(
                    select(ProviderWorkRecord).where(
                        ProviderWorkRecord.canonical_work_id == work.id
                    )
                )
            ).scalars().all()
            for record in provider_rows:
                raw = record.raw_metadata if isinstance(record.raw_metadata, dict) else {}
                _year, month = extract_publication_timing(raw)
                if month == publication_month:
                    return work
        return None

    async def create_canonical_work(self, candidate: WorkCandidate) -> CanonicalWork:
        work = CanonicalWork(
            id=uuid.uuid4(),
            title=candidate.title,
            normalized_title=candidate.normalized_title,
            publication_year=candidate.publication_year,
            normalized_first_author=candidate.normalized_first_author,
            doi=candidate.doi,
            arxiv_id=candidate.arxiv_id,
            pmid=candidate.pmid,
        )
        self.session.add(work)
        await self.session.flush()
        return work

    def enrich_canonical_work(
        self,
        work: CanonicalWork,
        candidate: WorkCandidate,
    ) -> None:
        if candidate.doi and not work.doi:
            work.doi = candidate.doi
        if candidate.arxiv_id and not work.arxiv_id:
            work.arxiv_id = candidate.arxiv_id
        if candidate.pmid and not work.pmid:
            work.pmid = candidate.pmid
        if candidate.publication_year and work.publication_year is None:
            work.publication_year = candidate.publication_year
        if candidate.normalized_first_author and not work.normalized_first_author:
            work.normalized_first_author = candidate.normalized_first_author
        if candidate.title and (not work.title or len(candidate.title) > len(work.title)):
            work.title = candidate.title
            work.normalized_title = candidate.normalized_title

    async def upsert_provider_record(
        self,
        candidate: WorkCandidate,
        canonical: CanonicalWork,
    ) -> tuple[ProviderWorkRecord, bool]:
        existing = await self.get_provider_record(
            candidate.provider,
            candidate.provider_work_id,
        )
        now = datetime.now(timezone.utc)
        if existing is None:
            record = ProviderWorkRecord(
                id=uuid.uuid4(),
                canonical_work_id=canonical.id,
                provider=candidate.provider,
                provider_work_id=candidate.provider_work_id,
                raw_metadata=candidate.raw_metadata,
                retrieved_at=now,
            )
            self.session.add(record)
            await self.session.flush()
            return record, True

        existing.canonical_work_id = canonical.id
        existing.raw_metadata = candidate.raw_metadata
        existing.retrieved_at = now
        await self.session.flush()
        return existing, False

    async def replace_work_authorships(
        self,
        *,
        canonical_work_id: uuid.UUID,
        provider: str,
        provider_work_id: str,
        raw_metadata: dict[str, Any] | None,
    ) -> list[WorkAuthorship]:
        """Replace persisted authorships for one provider snapshot of a work.

        `work_authorships.canonical_author_id` is authoritative for canonical
        author-work membership. `author_works` is maintained here as a derived
        provider-work index for existing author-identity overlap code.
        """
        authorship_rows = _authorships_from_raw_metadata(
            raw_metadata, provider=provider
        )

        existing = (
            (
                await self.session.execute(
                    select(WorkAuthorship).where(
                        WorkAuthorship.canonical_work_id == canonical_work_id,
                        WorkAuthorship.provider == provider,
                    )
                )
            )
            .scalars()
            .all()
        )
        for row in existing:
            await self.session.delete(row)
        if existing:
            await self.session.flush()

        provider_author_ids = sorted(
            {
                author_id
                for row in authorship_rows
                if (
                    author_id := _canonical_provider_author_id(
                        provider, row.get("provider_author_id")
                    )
                )
            }
        )
        provider_record_by_author_id: dict[str, ProviderAuthorRecord] = {}
        if provider_author_ids:
            provider_records = (
                (
                    await self.session.execute(
                        select(ProviderAuthorRecord).where(
                            ProviderAuthorRecord.provider == provider,
                            ProviderAuthorRecord.provider_author_id.in_(provider_author_ids),
                        )
                    )
                )
                .scalars()
                .all()
            )
            for record in provider_records:
                provider_record_by_author_id[record.provider_author_id] = record

        created: list[WorkAuthorship] = []
        for row in authorship_rows:
            provider_author_id = _canonical_provider_author_id(
                provider, row.get("provider_author_id")
            )
            provider_record = (
                provider_record_by_author_id.get(provider_author_id)
                if provider_author_id
                else None
            )
            canonical_author_id = None
            if provider_record is not None:
                canonical_author_id = provider_record.canonical_author_id
            authorship = WorkAuthorship(
                id=uuid.uuid4(),
                canonical_work_id=canonical_work_id,
                provider=provider,
                provider_author_id=provider_author_id,
                canonical_author_id=canonical_author_id,
                display_name=row["display_name"],
                author_position=int(row["author_position"]),
                orcid=row.get("orcid"),
                institutions=row.get("institutions") or [],
                institution_ids=row.get("institution_ids") or [],
                countries=row.get("countries") or [],
                raw_metadata=row.get("raw_metadata"),
            )
            self.session.add(authorship)
            created.append(authorship)
            if provider_record is not None:
                await self.ensure_author_work(
                    provider_record_id=provider_record.id,
                    provider_work_id=provider_work_id,
                    provider=provider,
                    title=raw_metadata.get("title") if isinstance(raw_metadata, dict) else None,
                    publication_year=(
                        raw_metadata.get("publication_year")
                        if isinstance(raw_metadata, dict)
                        else None
                    ),
                )
        if created:
            await self.session.flush()
        return created

    async def ensure_author_work(
        self,
        *,
        provider_record_id: uuid.UUID,
        provider_work_id: str,
        provider: str,
        title: str | None = None,
        publication_year: int | None = None,
    ) -> tuple[AuthorWork, bool]:
        existing = (
            await self.session.execute(
                select(AuthorWork).where(
                    AuthorWork.provider_author_record_id == provider_record_id,
                    AuthorWork.work_id == provider_work_id,
                )
            )
        ).scalar_one_or_none()
        if existing is not None:
            if title and not existing.title:
                existing.title = title
            if publication_year and existing.publication_year is None:
                existing.publication_year = publication_year
            return existing, False

        row = AuthorWork(
            id=uuid.uuid4(),
            provider_author_record_id=provider_record_id,
            work_id=provider_work_id,
            work_id_type=provider,
            title=title,
            publication_year=publication_year,
        )
        self.session.add(row)
        await self.session.flush()
        return row, True

    async def upsert_grant_match(
        self,
        *,
        canonical_work_id: uuid.UUID,
        provider: str,
        grant_number: str,
        normalized_grant_number: str,
        verified: bool,
        match_type: str,
        matched_text: str | None = None,
        raw_metadata: dict[str, Any] | None = None,
    ) -> tuple[WorkGrantMatch, bool]:
        stmt = select(WorkGrantMatch).where(
            WorkGrantMatch.canonical_work_id == canonical_work_id,
            WorkGrantMatch.provider == provider,
            WorkGrantMatch.normalized_grant_number == normalized_grant_number,
        )
        result = await self.session.execute(stmt)
        existing = result.scalar_one_or_none()
        now = datetime.now(timezone.utc)
        if existing is None:
            match = WorkGrantMatch(
                id=uuid.uuid4(),
                canonical_work_id=canonical_work_id,
                provider=provider,
                grant_number=grant_number,
                normalized_grant_number=normalized_grant_number,
                verified=verified,
                match_type=match_type,
                matched_text=matched_text,
                raw_metadata=raw_metadata,
                retrieved_at=now,
            )
            self.session.add(match)
            await self.session.flush()
            return match, True

        existing.grant_number = grant_number
        existing.verified = verified
        existing.match_type = match_type
        existing.matched_text = matched_text
        existing.raw_metadata = raw_metadata
        existing.retrieved_at = now
        await self.session.flush()
        return existing, False

    async def create_search_session(
        self,
        *,
        provider: str,
        entity: str,
        query: str,
        normalized_query: str,
        filters: dict[str, Any] | None,
        expires_at: datetime,
    ) -> SearchSession:
        session_row = SearchSession(
            id=uuid.uuid4(),
            provider=provider,
            entity=entity,
            query=query,
            normalized_query=normalized_query,
            filters=filters,
            expires_at=expires_at,
        )
        self.session.add(session_row)
        await self.session.flush()
        return session_row

    async def get_search_session(self, session_id: uuid.UUID) -> SearchSession | None:
        stmt = select(SearchSession).where(SearchSession.id == session_id)
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def list_session_entity_ids(
        self,
        search_session_id: uuid.UUID,
        *,
        canonical_entity_type: str = "work",
    ) -> set[uuid.UUID]:
        stmt = select(SearchSessionResult.canonical_entity_id).where(
            SearchSessionResult.search_session_id == search_session_id,
            SearchSessionResult.canonical_entity_type == canonical_entity_type,
        )
        result = await self.session.execute(stmt)
        return {row[0] for row in result.all()}

    async def next_session_position(self, search_session_id: uuid.UUID) -> int:
        stmt = select(SearchSessionResult.position).where(
            SearchSessionResult.search_session_id == search_session_id
        )
        result = await self.session.execute(stmt)
        positions = [row[0] for row in result.all()]
        return (max(positions) + 1) if positions else 0

    async def add_session_result(
        self,
        *,
        search_session_id: uuid.UUID,
        canonical_entity_id: uuid.UUID,
        position: int,
        first_seen_page: int,
        canonical_entity_type: str = "work",
    ) -> SearchSessionResult | None:
        existing_ids = await self.list_session_entity_ids(
            search_session_id,
            canonical_entity_type=canonical_entity_type,
        )
        if canonical_entity_id in existing_ids:
            return None
        row = SearchSessionResult(
            id=uuid.uuid4(),
            search_session_id=search_session_id,
            canonical_entity_type=canonical_entity_type,
            canonical_entity_id=canonical_entity_id,
            position=position,
            first_seen_page=first_seen_page,
        )
        self.session.add(row)
        await self.session.flush()
        return row

    async def get_cache_entry(self, cache_key: str) -> ProviderSearchCache | None:
        stmt = select(ProviderSearchCache).where(ProviderSearchCache.cache_key == cache_key)
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def upsert_cache_entry(
        self,
        *,
        cache_key: str,
        provider: str,
        entity: str,
        normalized_query: str,
        filters: dict[str, Any] | None,
        cursor: str | None,
        response: dict[str, Any],
        expires_at: datetime,
    ) -> ProviderSearchCache:
        existing = await self.get_cache_entry(cache_key)
        if existing is None:
            entry = ProviderSearchCache(
                id=uuid.uuid4(),
                cache_key=cache_key,
                provider=provider,
                entity=entity,
                normalized_query=normalized_query,
                filters=filters,
                cursor=cursor,
                response=response,
                expires_at=expires_at,
            )
            self.session.add(entry)
            await self.session.flush()
            return entry

        existing.provider = provider
        existing.entity = entity
        existing.normalized_query = normalized_query
        existing.filters = filters
        existing.cursor = cursor
        existing.response = response
        existing.expires_at = expires_at
        await self.session.flush()
        return existing
