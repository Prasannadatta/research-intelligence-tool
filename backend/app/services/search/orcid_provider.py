"""ORCID author search provider."""

from __future__ import annotations

import logging
from typing import Any

from app.core.config import get_settings
from app.integrations.orcid.client import search_orcid_authors
from app.services.author_resolution.candidate import AuthorCandidate
from app.services.search.base import BaseSearchProvider

logger = logging.getLogger(__name__)


def _current_employment(employments: list[dict[str, Any]]) -> dict[str, Any] | None:
    if not employments:
        return None
    open_ended = [row for row in employments if not row.get("end_date")]
    pool = open_ended or list(employments)

    def sort_key(row: dict[str, Any]) -> str:
        return str(row.get("start_date") or "")

    return max(pool, key=sort_key)


def author_candidate_to_search_result(candidate: AuthorCandidate) -> dict[str, Any]:
    """Map an ORCID AuthorCandidate onto the unified author-search row shape."""
    employments = list(candidate.raw_metadata.get("employments") or [])
    current = _current_employment(employments)
    institutions = [
        {
            "id": inst.id,
            "name": inst.name,
            "country_code": inst.country_code,
        }
        for inst in candidate.institutions
    ]
    primary_institution = None
    if current and (current.get("name") or current.get("id")):
        primary_institution = {
            "id": current.get("id"),
            "name": current.get("name"),
            "country_code": current.get("country_code"),
        }
    elif institutions:
        primary_institution = dict(institutions[0])

    works = [
        {
            "id": work.id,
            "id_type": work.id_type,
            "title": work.title,
            "publication_year": work.publication_year,
        }
        for work in candidate.works
    ]
    sample_papers = [
        {
            "result_id": f"doi:{work['id']}",
            "title": work.get("title"),
            "publication_year": work.get("publication_year"),
        }
        for work in works
        if work.get("id_type") == "doi" and work.get("id")
    ]
    orcid = candidate.orcid or candidate.provider_author_id
    return {
        "result_id": f"orcid:{orcid}",
        "result_type": "author",
        "openalex_id": None,
        "display_name": candidate.display_name,
        "alternative_names": list(candidate.aliases or []),
        "orcid": orcid,
        "primary_institution": primary_institution,
        "institutions": institutions,
        "employments": employments,
        "topics": [{"name": topic} for topic in candidate.topics if topic],
        "works_count": candidate.works_count,
        "cited_by_count": None,
        "source": "orcid",
        "sample_papers": sample_papers,
        "works": works,
    }


def _affiliation_from_filters(filters: dict[str, Any]) -> str | None:
    for key in ("affiliation", "institution_name", "institution_display_name"):
        text = " ".join(str(filters.get(key) or "").split())
        if text:
            return text
    institution_id = " ".join(str(filters.get("institution_id") or "").split())
    if not institution_id:
        return None
    from app.integrations.openalex.filters import is_valid_institution_id

    if is_valid_institution_id(institution_id):
        return None
    return institution_id


async def search_orcid_author_results(
    *,
    query: str | None,
    limit: int,
    filters: dict[str, Any] | None = None,
    enrich: bool = True,
) -> list[dict[str, Any]]:
    """Return ORCID author rows. Never raises — empty list on failure."""
    filters = filters or {}
    affiliation = _affiliation_from_filters(filters)
    try:
        payload = await search_orcid_authors(
            query=query or "",
            affiliation=affiliation,
            limit=limit,
            enrich=enrich,
        )
    except Exception:
        logger.warning("orcid_author_search_failed")
        return []

    results: list[dict[str, Any]] = []
    seen: set[str] = set()
    for item in payload.get("results") or []:
        candidate = item if isinstance(item, AuthorCandidate) else None
        if candidate is None:
            continue
        orcid = candidate.orcid or candidate.provider_author_id
        if not orcid or orcid in seen:
            continue
        seen.add(orcid)
        results.append(author_candidate_to_search_result(candidate))
    return results


class OrcidProvider(BaseSearchProvider):
    id = "orcid"
    label = "ORCID"

    @property
    def enabled(self) -> bool:
        return bool(get_settings().orcid_configured)

    @property
    def supported_entity_types(self) -> tuple[str, ...]:
        return ("authors",) if self.enabled else ()

    async def search_authors(
        self,
        *,
        query: str | None,
        cursor: str | None,
        limit: int,
        filters: dict[str, Any],
    ) -> dict[str, Any]:
        from app.integrations.orcid.normalize import normalize_orcid_id

        orcid_id = normalize_orcid_id(query)
        results = await search_orcid_author_results(
            query=query,
            limit=limit,
            filters=filters,
            enrich=bool(orcid_id),
        )
        cleaned = " ".join((query or "").split())
        return {
            "query": cleaned,
            "entity_type": "authors",
            "source": "orcid",
            "results": results,
            "next_cursor": None,
            "has_more": False,
        }

    async def search_works(
        self,
        *,
        query: str | None,
        cursor: str | None,
        limit: int,
        filters: dict[str, Any],
    ) -> dict[str, Any]:
        raise ValueError("ORCID search does not support works.")

    async def search_grants(
        self,
        *,
        query: str | None,
        cursor: str | None,
        limit: int,
        filters: dict[str, Any],
    ) -> dict[str, Any]:
        raise ValueError("ORCID search does not support grants.")
