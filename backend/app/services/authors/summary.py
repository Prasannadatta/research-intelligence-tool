"""Canonical author summary retrieval and enrichment."""

from __future__ import annotations

import asyncio
import logging
import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.config import get_settings
from app.db.models import (
    AuthorProfile,
    CanonicalAuthor,
    CanonicalAuthorInstitution,
    ProviderAuthorRecord,
)
from app.integrations.elsevier.client import elsevier_configured
from app.integrations.openalex.client import (
    OpenAlexApiError,
    fetch_openalex_author_payload,
    normalize_openalex_author,
)
from app.integrations.orcid.client import orcid_configured
from app.services.authors.affiliation_enrichment import (
    enrich_from_orcid,
    enrich_from_scopus,
    source_needs_enrichment,
)
from app.services.authors.openalex_enrichment import (
    extract_openalex_affiliations,
    extract_openalex_h_index,
    extract_openalex_topic_names,
)
from app.services.author_resolution.normalization import normalize_author_name
from app.services.author_resolution.repository import AuthorIdentityRepository

logger = logging.getLogger(__name__)

_enrich_locks: dict[str, asyncio.Lock] = {}
_enrich_locks_guard = asyncio.Lock()


class AuthorSummaryError(Exception):
    def __init__(self, message: str, *, status_code: int = 404) -> None:
        super().__init__(message)
        self.status_code = status_code


def _merge_optional_int(existing: int | None, incoming: int | None) -> int | None:
    if incoming is None:
        return existing
    if existing is None:
        return incoming
    return max(existing, incoming)


def _merge_optional_str(existing: str | None, incoming: str | None) -> str | None:
    if incoming is None or incoming == "":
        return existing
    return incoming


def _merge_topics(existing: list[str] | None, incoming: list[str]) -> list[str]:
    merged: list[str] = []
    seen: set[str] = set()
    for value in list(existing or []) + list(incoming or []):
        text = str(value).strip()
        key = text.lower()
        if not text or key in seen:
            continue
        seen.add(key)
        merged.append(text)
    return merged


def _merge_providers(existing: list[str] | None, incoming: list[str]) -> list[str]:
    return sorted({*(existing or []), *(incoming or [])})


def _institution_sort_key(row: CanonicalAuthorInstitution) -> tuple[Any, ...]:
    return (
        0 if row.is_current else 1,
        -(row.valid_to_year or row.valid_from_year or 0),
        row.institution_name or "",
    )


def _serialize_institution(row: CanonicalAuthorInstitution) -> dict[str, Any]:
    years = None
    if row.valid_from_year is not None or row.valid_to_year is not None:
        years = {
            "from": row.valid_from_year,
            "to": row.valid_to_year,
        }
    return {
        "id": row.institution_id,
        "name": row.institution_name,
        "department": row.department,
        "country_code": row.country_code,
        "current": bool(row.is_current),
        "years": years,
        "sources": [row.provider] if row.provider else [],
    }


def _mark_openalex_meta(profile: AuthorProfile) -> None:
    meta = dict(profile.enrichment_meta or {})
    meta["openalex"] = datetime.now(UTC).isoformat()
    profile.enrichment_meta = meta


def _has_usable_profile(profile: AuthorProfile | None) -> bool:
    if profile is None:
        return False
    return any(
        (
            profile.works_count is not None,
            profile.citation_count is not None,
            profile.h_index is not None,
            bool(profile.topics),
            bool(profile.orcid),
            bool(profile.enriched_at),
        )
    )


def _resolve_orcid(profile: AuthorProfile | None, canonical: CanonicalAuthor) -> str | None:
    if profile and profile.orcid:
        return str(profile.orcid).strip() or None
    for record in canonical.provider_records:
        if record.orcid:
            return str(record.orcid).strip() or None
        if record.provider == "orcid" and record.provider_author_id:
            return str(record.provider_author_id).strip() or None
    return None


def _pending_enrichment(
    profile: AuthorProfile | None,
    canonical: CanonicalAuthor,
) -> dict[str, Any]:
    settings = get_settings()
    oa_ttl = getattr(settings, "author_profile_freshness_days", 14)
    orcid_ttl = getattr(settings, "author_profile_orcid_enrichment_ttl_days", 14)
    scopus_ttl = getattr(settings, "author_profile_scopus_enrichment_ttl_days", 30)

    has_openalex = any(r.provider == "openalex" for r in canonical.provider_records)
    orcid = _resolve_orcid(profile, canonical)
    settings_obj = get_settings()
    openalex_ok = bool(getattr(settings_obj, "openalex_configured", False))
    orcid_ok = orcid_configured()
    scopus_ok = elsevier_configured()

    pending: list[str] = []
    if (
        has_openalex
        and openalex_ok
        and _has_usable_profile(profile)
        and source_needs_enrichment(profile, "openalex", ttl_days=oa_ttl)
    ):
        # Stale OA refresh is lazy — cold profiles sync synchronously on GET.
        pending.append("openalex")
    if orcid and orcid_ok and source_needs_enrichment(profile, "orcid", ttl_days=orcid_ttl):
        pending.append("orcid")
    if orcid and scopus_ok and source_needs_enrichment(profile, "scopus", ttl_days=scopus_ttl):
        pending.append("scopus")

    sources = {
        "openalex": (
            not source_needs_enrichment(profile, "openalex", ttl_days=oa_ttl)
            if has_openalex
            else False
        ),
        "orcid": (
            not source_needs_enrichment(profile, "orcid", ttl_days=orcid_ttl)
            if orcid
            else False
        ),
        "scopus": (
            not source_needs_enrichment(profile, "scopus", ttl_days=scopus_ttl)
            if orcid
            else False
        ),
    }
    return {"pending": pending, "sources": sources}


def _collect_provider_ids(
    canonical: CanonicalAuthor,
    profile: AuthorProfile | None,
) -> dict[str, list[str]]:
    """Stable provider author IDs only — never inferred from display name."""
    buckets: dict[str, list[str]] = {
        "openalex": [],
        "orcid": [],
        "scopus": [],
        "arxiv": [],
    }
    seen: dict[str, set[str]] = {key: set() for key in buckets}

    def _add(provider: str, value: str | None) -> None:
        text = str(value or "").strip()
        if not text:
            return
        key = provider.lower()
        if key not in buckets:
            buckets[key] = []
            seen[key] = set()
        if text in seen[key]:
            return
        seen[key].add(text)
        buckets[key].append(text)

    for record in canonical.provider_records or []:
        provider = str(record.provider or "").strip().lower()
        if not provider:
            continue
        _add(provider, record.provider_author_id)
        if record.orcid:
            _add("orcid", record.orcid)

    orcid = _resolve_orcid(profile, canonical)
    if orcid:
        _add("orcid", orcid)

    return buckets


def _build_summary(
    canonical: CanonicalAuthor,
    profile: AuthorProfile | None,
    institutions: list[CanonicalAuthorInstitution],
    *,
    unresolved: bool = False,
) -> dict[str, Any]:
    aliases = sorted(
        {
            alias.alias
            for alias in canonical.aliases
            if alias.alias and alias.alias != canonical.preferred_name
        }
    )
    providers = list(profile.providers or []) if profile and profile.providers else []
    if not providers:
        providers = sorted(
            {record.provider for record in canonical.provider_records if record.provider}
        )

    updated_at = profile.updated_at if profile else canonical.updated_at
    enrichment = _pending_enrichment(profile, canonical)
    orcid = _resolve_orcid(profile, canonical)

    return {
        "id": str(canonical.id),
        "display_name": canonical.preferred_name,
        "aliases": aliases,
        "institutions": [_serialize_institution(row) for row in institutions],
        "orcid": orcid,
        "provider_ids": _collect_provider_ids(canonical, profile),
        "topics": list(profile.topics or []) if profile and profile.topics else [],
        "works_count": profile.works_count if profile else None,
        "citation_count": profile.citation_count if profile else None,
        "h_index": profile.h_index if profile else None,
        "providers": providers,
        "updated_at": updated_at.isoformat() if updated_at else None,
        "unresolved": unresolved,
        "enrichment": enrichment,
    }


async def _load_profile_bundle(
    session: AsyncSession,
    canonical_id: uuid.UUID,
) -> tuple[CanonicalAuthor | None, AuthorProfile | None, list[CanonicalAuthorInstitution]]:
    canonical_stmt = (
        select(CanonicalAuthor)
        .where(CanonicalAuthor.id == canonical_id)
        .options(
            selectinload(CanonicalAuthor.aliases),
            selectinload(CanonicalAuthor.provider_records),
        )
        # Enrichment may attach new provider rows in-session; refresh the identity map.
        .execution_options(populate_existing=True)
    )
    canonical = (await session.execute(canonical_stmt)).scalar_one_or_none()
    if canonical is None:
        return None, None, []

    profile = (
        await session.execute(
            select(AuthorProfile).where(AuthorProfile.canonical_author_id == canonical_id)
        )
    ).scalar_one_or_none()

    institutions = list(
        (
            await session.execute(
                select(CanonicalAuthorInstitution).where(
                    CanonicalAuthorInstitution.canonical_author_id == canonical_id
                )
            )
        )
        .scalars()
        .all()
    )
    institutions.sort(key=_institution_sort_key)
    return canonical, profile, institutions


async def _upsert_profile_from_openalex(
    session: AsyncSession,
    canonical: CanonicalAuthor,
    profile: AuthorProfile | None,
    openalex_payload: dict[str, Any],
    raw_openalex: dict[str, Any],
) -> tuple[AuthorProfile, list[CanonicalAuthorInstitution]]:
    topics = extract_openalex_topic_names(raw_openalex)
    h_index = extract_openalex_h_index(raw_openalex)
    orcid = openalex_payload.get("orcid")
    works_count = openalex_payload.get("works_count")
    citation_count = openalex_payload.get("cited_by_count")

    if profile is None:
        profile = AuthorProfile(canonical_author_id=canonical.id)
        session.add(profile)

    profile.orcid = _merge_optional_str(profile.orcid, orcid)
    profile.works_count = _merge_optional_int(profile.works_count, works_count)
    profile.citation_count = _merge_optional_int(profile.citation_count, citation_count)
    profile.h_index = _merge_optional_int(profile.h_index, h_index)
    profile.topics = _merge_topics(profile.topics, topics)
    profile.providers = _merge_providers(profile.providers, ["openalex"])
    profile.enriched_at = datetime.now(UTC)
    _mark_openalex_meta(profile)
    await session.flush()

    affiliation_rows = extract_openalex_affiliations(raw_openalex)
    existing = list(
        (
            await session.execute(
                select(CanonicalAuthorInstitution).where(
                    CanonicalAuthorInstitution.canonical_author_id == canonical.id
                )
            )
        )
        .scalars()
        .all()
    )
    by_key = {row.institution_key: row for row in existing}

    for row in affiliation_rows:
        key = row["institution_key"]
        provider = row.get("provider") or "openalex"
        current = by_key.get(key)
        if current is not None and current.provider and current.provider != provider:
            key = f"{provider}:{key}"
            current = by_key.get(key)

        if current is None:
            current = CanonicalAuthorInstitution(
                id=uuid.uuid4(),
                canonical_author_id=canonical.id,
                institution_key=key,
                provider=provider,
            )
            session.add(current)
            by_key[key] = current

        if row.get("institution_name"):
            if not current.institution_name or current.provider == provider:
                current.institution_name = row["institution_name"]
        if row.get("institution_id") and not current.institution_id:
            current.institution_id = row["institution_id"]
        if row.get("country_code") and not current.country_code:
            current.country_code = row["country_code"]
        # Fill missing department only — never overwrite ORCID/Scopus values.
        if row.get("department") and not current.department:
            current.department = row["department"]
        if row.get("valid_from_year") is not None:
            current.valid_from_year = _merge_optional_int(
                current.valid_from_year, row["valid_from_year"]
            )
        if row.get("valid_to_year") is not None:
            current.valid_to_year = _merge_optional_int(
                current.valid_to_year, row["valid_to_year"]
            )
        if row.get("is_current"):
            current.is_current = True
        if not current.provider:
            current.provider = provider

    await session.flush()

    institutions = sorted(by_key.values(), key=_institution_sort_key)
    return profile, institutions


async def _enrich_from_openalex(
    session: AsyncSession,
    canonical: CanonicalAuthor,
    profile: AuthorProfile | None,
    institutions: list[CanonicalAuthorInstitution],
) -> tuple[AuthorProfile | None, list[CanonicalAuthorInstitution]]:
    settings = get_settings()
    if not settings.openalex_configured:
        return profile, institutions

    openalex_record = next(
        (record for record in canonical.provider_records if record.provider == "openalex"),
        None,
    )
    if openalex_record is None:
        return profile, institutions

    try:
        raw_openalex = await fetch_openalex_author_payload(openalex_record.provider_author_id)
        openalex_payload = normalize_openalex_author(raw_openalex) or {}
    except OpenAlexApiError as exc:
        logger.warning("OpenAlex enrichment failed for %s: %s", canonical.id, exc)
        return profile, institutions

    profile, institutions = await _upsert_profile_from_openalex(
        session,
        canonical,
        profile,
        openalex_payload,
        raw_openalex,
    )
    return profile, institutions


async def _enrich_lock_for(canonical_id: str) -> asyncio.Lock:
    async with _enrich_locks_guard:
        lock = _enrich_locks.get(canonical_id)
        if lock is None:
            lock = asyncio.Lock()
            _enrich_locks[canonical_id] = lock
        return lock


def reset_author_summary_enrich_locks_for_tests() -> None:
    _enrich_locks.clear()


async def get_author_summary(
    session: AsyncSession | None,
    canonical_author_id: str,
) -> dict[str, Any]:
    """Return local profile immediately. Sync OpenAlex only when no usable snapshot exists."""
    if session is None:
        raise AuthorSummaryError(
            "Author metadata storage is unavailable.",
            status_code=503,
        )

    try:
        canonical_uuid = uuid.UUID(str(canonical_author_id).strip())
    except (TypeError, ValueError) as exc:
        raise AuthorSummaryError(
            "Invalid canonical author ID.",
            status_code=422,
        ) from exc

    canonical, profile, institutions = await _load_profile_bundle(session, canonical_uuid)
    if canonical is None:
        raise AuthorSummaryError("Author not found.", status_code=404)

    # Cold start only: block once for OpenAlex base profile so the hover card has metrics.
    if not _has_usable_profile(profile):
        profile, institutions = await _enrich_from_openalex(
            session, canonical, profile, institutions
        )
        try:
            await session.commit()
        except Exception:
            logger.exception("Failed to commit author summary OpenAlex sync")
            await session.rollback()
        canonical, profile, institutions = await _load_profile_bundle(
            session, canonical_uuid
        )
        if canonical is None:
            raise AuthorSummaryError("Author not found.", status_code=404)

    return _build_summary(canonical, profile, institutions)


async def enrich_author_summary(
    session: AsyncSession | None,
    canonical_author_id: str,
) -> dict[str, Any]:
    """Lazy ORCID/Scopus (+ stale OpenAlex) enrichment. Failures never break the card."""
    if session is None:
        raise AuthorSummaryError(
            "Author metadata storage is unavailable.",
            status_code=503,
        )

    try:
        canonical_uuid = uuid.UUID(str(canonical_author_id).strip())
    except (TypeError, ValueError) as exc:
        raise AuthorSummaryError(
            "Invalid canonical author ID.",
            status_code=422,
        ) from exc

    lock = await _enrich_lock_for(str(canonical_uuid))
    async with lock:
        canonical, profile, institutions = await _load_profile_bundle(
            session, canonical_uuid
        )
        if canonical is None:
            raise AuthorSummaryError("Author not found.", status_code=404)

        settings = get_settings()
        oa_ttl = getattr(settings, "author_profile_freshness_days", 14)
        orcid_ttl = getattr(settings, "author_profile_orcid_enrichment_ttl_days", 14)
        scopus_ttl = getattr(settings, "author_profile_scopus_enrichment_ttl_days", 30)

        contacted: list[str] = []

        if source_needs_enrichment(profile, "openalex", ttl_days=oa_ttl):
            before = profile.enriched_at if profile else None
            profile, institutions = await _enrich_from_openalex(
                session, canonical, profile, institutions
            )
            after = profile.enriched_at if profile else None
            if after is not None and after != before:
                contacted.append("openalex")

        if profile is None:
            profile = AuthorProfile(canonical_author_id=canonical.id)
            session.add(profile)
            await session.flush()

        try:
            if source_needs_enrichment(profile, "orcid", ttl_days=orcid_ttl):
                if await enrich_from_orcid(session, canonical=canonical, profile=profile):
                    contacted.append("orcid")
        except Exception:
            logger.exception("ORCID enrichment crashed for %s", canonical.id)

        try:
            if source_needs_enrichment(profile, "scopus", ttl_days=scopus_ttl):
                if await enrich_from_scopus(session, canonical=canonical, profile=profile):
                    contacted.append("scopus")
        except Exception:
            logger.exception("Scopus enrichment crashed for %s", canonical.id)

        try:
            await session.commit()
        except Exception:
            logger.exception("Failed to commit author summary enrichment")
            await session.rollback()

        canonical, profile, institutions = await _load_profile_bundle(
            session, canonical_uuid
        )
        if canonical is None:
            raise AuthorSummaryError("Author not found.", status_code=404)

        summary = _build_summary(canonical, profile, institutions)
        summary["enrichment"] = {
            **summary.get("enrichment", {}),
            "contacted": contacted,
        }
        return summary


async def get_author_summary_by_openalex_id(
    session: AsyncSession | None,
    openalex_id: str,
) -> dict[str, Any]:
    if session is None:
        raise AuthorSummaryError(
            "Author metadata storage is unavailable.",
            status_code=503,
        )

    repo = AuthorIdentityRepository(session)
    record = await repo.get_provider_record("openalex", openalex_id.strip())
    if record is not None and record.canonical_author_id is not None:
        return await get_author_summary(session, str(record.canonical_author_id))

    settings = get_settings()
    if not settings.openalex_configured:
        raise AuthorSummaryError("Author metadata is unavailable.", status_code=503)

    try:
        raw_openalex = await fetch_openalex_author_payload(openalex_id)
        openalex_payload = normalize_openalex_author(raw_openalex) or {}
    except OpenAlexApiError as exc:
        raise AuthorSummaryError(str(exc), status_code=exc.status_code) from exc

    display_name = openalex_payload.get("display_name") or "Unknown author"
    normalized = normalize_author_name(display_name)
    canonical = await repo.create_canonical_author(
        preferred_name=display_name,
        normalized_name=normalized or display_name.lower(),
        surname=None,
        first_initial=None,
        resolution_status="unresolved",
        aliases=list(openalex_payload.get("alternative_names") or []),
    )

    from app.services.author_resolution.candidate import candidate_from_provider_result

    candidate = candidate_from_provider_result(
        {**openalex_payload, "result_type": "author", "source": "openalex"}
    )
    if candidate is not None:
        record = await repo.upsert_provider_record(candidate)
        await repo.attach_record_to_canonical(record, canonical, status="unresolved")

    profile, institutions = await _upsert_profile_from_openalex(
        session,
        canonical,
        None,
        openalex_payload,
        raw_openalex,
    )
    try:
        await session.commit()
    except Exception:
        logger.exception("Failed to commit OpenAlex-only author summary")
        await session.rollback()
        raise AuthorSummaryError(
            "Author metadata could not be saved.",
            status_code=503,
        ) from None

    # Reload with selectinload — freshly created objects do not have aliases/provider
    # collections populated in-memory, and lazy load raises MissingGreenlet.
    loaded_canonical, loaded_profile, loaded_institutions = await _load_profile_bundle(
        session, canonical.id
    )
    if loaded_canonical is None:
        return _build_summary(canonical, profile, institutions, unresolved=True)
    return _build_summary(
        loaded_canonical,
        loaded_profile or profile,
        loaded_institutions or institutions,
        unresolved=True,
    )


async def lookup_canonical_ids_for_openalex_authors(
    session: AsyncSession | None,
    openalex_ids: set[str],
) -> dict[str, dict[str, Any]]:
    if session is None or not openalex_ids:
        return {}

    stmt = (
        select(ProviderAuthorRecord)
        .where(
            ProviderAuthorRecord.provider == "openalex",
            ProviderAuthorRecord.provider_author_id.in_(sorted(openalex_ids)),
        )
        .options(selectinload(ProviderAuthorRecord.canonical_author))
    )
    try:
        rows = (await session.execute(stmt)).scalars().all()
    except SQLAlchemyError:
        logger.warning(
            "OpenAlex author canonical lookup skipped because identity tables are unavailable",
            exc_info=True,
        )
        await session.rollback()
        return {}

    mapping: dict[str, dict[str, Any]] = {}
    for row in rows:
        entry = mapping.setdefault(
            row.provider_author_id,
            {
                "canonical_author_id": None,
                "orcid": row.orcid,
                "provider_ids": {"openalex": [row.provider_author_id], "orcid": [], "arxiv": []},
            },
        )
        if row.orcid:
            entry["provider_ids"]["orcid"] = sorted(
                {*(entry["provider_ids"].get("orcid") or []), row.orcid}
            )
        if row.canonical_author_id is not None:
            entry["canonical_author_id"] = str(row.canonical_author_id)
    return mapping
