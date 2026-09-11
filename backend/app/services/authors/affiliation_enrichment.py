"""Source-aware ORCID / Scopus affiliation enrichment for author hover cards."""

from __future__ import annotations

import logging
import time
import uuid
from collections import OrderedDict
from datetime import UTC, datetime
from threading import Lock
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import AuthorProfile, CanonicalAuthor, CanonicalAuthorInstitution
from app.integrations.elsevier.author_retrieval import parse_scopus_author_retrieval
from app.integrations.elsevier.client import ElsevierApiError, ElsevierClient, elsevier_configured
from app.integrations.orcid.client import OrcidApiError, OrcidClient, orcid_configured
from app.integrations.orcid.normalize import normalize_orcid_id, parse_employments_payload

logger = logging.getLogger(__name__)

CACHE_TTL_SECONDS = 12 * 60 * 60
CACHE_MAX_ENTRIES = 500


class _TtlCache:
    def __init__(self, *, ttl_seconds: int, max_entries: int) -> None:
        self._ttl_seconds = ttl_seconds
        self._max_entries = max_entries
        self._store: OrderedDict[str, tuple[float, Any]] = OrderedDict()
        self._lock = Lock()

    def get(self, key: str) -> Any | None:
        now = time.monotonic()
        with self._lock:
            item = self._store.get(key)
            if item is None:
                return None
            expires_at, value = item
            if expires_at <= now:
                self._store.pop(key, None)
                return None
            self._store.move_to_end(key)
            return value

    def set(self, key: str, value: Any) -> None:
        expires_at = time.monotonic() + self._ttl_seconds
        with self._lock:
            self._store[key] = (expires_at, value)
            self._store.move_to_end(key)
            while len(self._store) > self._max_entries:
                self._store.popitem(last=False)

    def clear(self) -> None:
        with self._lock:
            self._store.clear()


_scopus_author_cache = _TtlCache(ttl_seconds=CACHE_TTL_SECONDS, max_entries=CACHE_MAX_ENTRIES)
_orcid_employments_cache = _TtlCache(ttl_seconds=CACHE_TTL_SECONDS, max_entries=CACHE_MAX_ENTRIES)


def reset_author_enrichment_caches_for_tests() -> None:
    _scopus_author_cache.clear()
    _orcid_employments_cache.clear()


def _merge_optional_str(existing: str | None, incoming: str | None) -> str | None:
    if incoming is None or incoming == "":
        return existing
    if existing is None or existing == "":
        return incoming
    return existing


def _merge_optional_int(existing: int | None, incoming: int | None) -> int | None:
    if incoming is None:
        return existing
    if existing is None:
        return incoming
    return max(existing, incoming)


def _upsert_source_affiliation(
    *,
    session: AsyncSession,
    by_key: dict[str, CanonicalAuthorInstitution],
    canonical_id: uuid.UUID,
    row: dict[str, Any],
) -> None:
    """Insert/update affiliation without overwriting another provider's values."""
    key = str(row.get("institution_key") or "").strip()
    if not key:
        return
    provider = str(row.get("provider") or "").strip().lower() or None
    current = by_key.get(key)
    if current is not None and current.provider and provider and current.provider != provider:
        key = f"{provider}:{key}"
        current = by_key.get(key)

    if current is None:
        current = CanonicalAuthorInstitution(
            id=uuid.uuid4(),
            canonical_author_id=canonical_id,
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
    # Department: fill missing only — never overwrite a conflicting value.
    if row.get("department") and not current.department:
        current.department = row["department"]
    if row.get("is_current"):
        current.is_current = True
    if provider and not current.provider:
        current.provider = provider


async def _load_institutions_by_key(
    session: AsyncSession,
    canonical_id: uuid.UUID,
) -> dict[str, CanonicalAuthorInstitution]:
    rows = list(
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
    return {row.institution_key: row for row in rows}


def _mark_source(profile: AuthorProfile, source: str) -> None:
    meta = dict(profile.enrichment_meta or {})
    meta[source] = datetime.now(UTC).isoformat()
    profile.enrichment_meta = meta
    providers = list(profile.providers or [])
    if source not in providers:
        providers.append(source)
    profile.providers = sorted(set(providers))


async def enrich_from_orcid(
    session: AsyncSession,
    *,
    canonical: CanonicalAuthor,
    profile: AuthorProfile,
) -> bool:
    """Pull ORCID employment/affiliations. Returns True when provider was contacted."""
    if not orcid_configured():
        return False
    orcid = normalize_orcid_id(profile.orcid)
    if not orcid:
        for record in canonical.provider_records:
            orcid = normalize_orcid_id(record.orcid) or (
                normalize_orcid_id(record.provider_author_id)
                if record.provider == "orcid"
                else None
            )
            if orcid:
                break
    if not orcid:
        return False

    cache_key = f"orcid-employments|{orcid}"
    payload = _orcid_employments_cache.get(cache_key)
    contacted = False
    if payload is None:
        contacted = True
        try:
            payload = await OrcidClient().get_employments(orcid)
        except OrcidApiError as exc:
            logger.info("orcid_enrichment_failed author=%s error=%s", canonical.id, exc)
            _mark_source(profile, "orcid")  # avoid tight retry loops on hard failures
            return True
        _orcid_employments_cache.set(cache_key, payload)

    profile.orcid = _merge_optional_str(profile.orcid, orcid)
    employments = parse_employments_payload(payload)
    by_key = await _load_institutions_by_key(session, canonical.id)
    for employment in employments:
        org_id = employment.get("id")
        name = employment.get("name")
        key = (
            f"orcid:{org_id}"
            if org_id
            else f"orcid-name:{(name or '').casefold()}"
        )
        end_date = employment.get("end_date") or ""
        is_current = not bool(str(end_date).strip())
        _upsert_source_affiliation(
            session=session,
            by_key=by_key,
            canonical_id=canonical.id,
            row={
                "institution_key": key,
                "institution_id": org_id,
                "institution_name": name,
                "department": employment.get("department"),
                "country_code": employment.get("country_code"),
                "is_current": is_current,
                "provider": "orcid",
            },
        )

    _mark_source(profile, "orcid")
    await session.flush()
    return contacted


async def enrich_from_scopus(
    session: AsyncSession,
    *,
    canonical: CanonicalAuthor,
    profile: AuthorProfile,
) -> bool:
    """Pull Scopus author/org enrichment by ORCID. Returns True when provider contacted."""
    if not elsevier_configured():
        return False
    orcid = normalize_orcid_id(profile.orcid)
    if not orcid:
        return False

    cache_key = f"scopus-author|{orcid}"
    parsed = _scopus_author_cache.get(cache_key)
    contacted = False
    if parsed is None:
        contacted = True
        try:
            response = await ElsevierClient().get_author_by_orcid(orcid)
        except ElsevierApiError as exc:
            logger.info("scopus_enrichment_failed author=%s error=%s", canonical.id, exc)
            _mark_source(profile, "scopus")
            return True
        if response.status_code == 404:
            _scopus_author_cache.set(cache_key, {"affiliations": []})
            _mark_source(profile, "scopus")
            return True
        if response.status_code != 200:
            logger.info(
                "scopus_enrichment_http author=%s status=%s",
                canonical.id,
                response.status_code,
            )
            _mark_source(profile, "scopus")
            return True
        try:
            payload = response.json()
        except Exception:
            _mark_source(profile, "scopus")
            return True
        parsed = parse_scopus_author_retrieval(payload)
        _scopus_author_cache.set(cache_key, parsed)

    by_key = await _load_institutions_by_key(session, canonical.id)
    for row in parsed.get("affiliations") or []:
        _upsert_source_affiliation(
            session=session,
            by_key=by_key,
            canonical_id=canonical.id,
            row=row,
        )

    scopus_author_id = str(parsed.get("scopus_author_id") or "").strip()
    if scopus_author_id:
        already_linked = any(
            record.provider == "scopus"
            and str(record.provider_author_id) == scopus_author_id
            for record in (canonical.provider_records or [])
        )
        if not already_linked:
            from app.services.author_resolution.candidate import AuthorCandidate
            from app.services.author_resolution.normalization import normalize_author_name
            from app.services.author_resolution.repository import AuthorIdentityRepository

            display_name = canonical.preferred_name or "Unknown author"
            normalized = normalize_author_name(display_name) or display_name.lower()
            repo = AuthorIdentityRepository(session)
            try:
                record = await repo.upsert_provider_record(
                    AuthorCandidate(
                        provider="scopus",
                        provider_author_id=scopus_author_id,
                        display_name=display_name,
                        normalized_name=normalized,
                        surname=canonical.surname,
                        first_initial=canonical.first_initial,
                        orcid=normalize_orcid_id(profile.orcid) or orcid,
                        works_count=parsed.get("document_count"),
                        raw_metadata={
                            "scopus_author_id": scopus_author_id,
                            "source": "author_retrieval",
                        },
                    )
                )
                if record.canonical_author_id is None:
                    await repo.attach_record_to_canonical(
                        record,
                        canonical,
                        status=canonical.resolution_status or "merged",
                    )
            except Exception:
                logger.exception(
                    "scopus_provider_record_upsert_failed author=%s scopus_id=%s",
                    canonical.id,
                    scopus_author_id,
                )

    # Optional metrics: fill gaps only; do not overwrite OpenAlex counts.
    if parsed.get("document_count") is not None and profile.works_count is None:
        profile.works_count = int(parsed["document_count"])
    if parsed.get("h_index") is not None and profile.h_index is None:
        profile.h_index = int(parsed["h_index"])

    _mark_source(profile, "scopus")
    await session.flush()
    return contacted


def source_needs_enrichment(
    profile: AuthorProfile | None,
    source: str,
    *,
    ttl_days: int,
) -> bool:
    from datetime import timedelta

    if profile is None:
        return True
    meta = profile.enrichment_meta if isinstance(profile.enrichment_meta, dict) else {}
    stamp = meta.get(source)
    if stamp:
        try:
            enriched_at = datetime.fromisoformat(str(stamp).replace("Z", "+00:00"))
        except ValueError:
            return True
        if enriched_at.tzinfo is None:
            enriched_at = enriched_at.replace(tzinfo=UTC)
        return enriched_at < datetime.now(UTC) - timedelta(days=ttl_days)

    # Legacy profiles (no per-source meta): use overall enriched_at when source listed.
    providers = {str(value).lower() for value in (profile.providers or [])}
    if source in providers and profile.enriched_at is not None:
        enriched_at = profile.enriched_at
        if enriched_at.tzinfo is None:
            enriched_at = enriched_at.replace(tzinfo=UTC)
        return enriched_at < datetime.now(UTC) - timedelta(days=ttl_days)
    return True
