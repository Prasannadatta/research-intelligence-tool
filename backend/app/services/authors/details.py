"""Author details page payload: summary plus stored grants/publications."""

from __future__ import annotations

from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.services.analysis.author_insights import AuthorInsightsService
from app.services.authors.summary import get_author_summary

PUBLICATION_PREVIEW_LIMIT = 12


def _publication_sort_key(item: dict[str, Any]) -> tuple[Any, ...]:
    return (
        -(item.get("citation_count") if item.get("citation_count") is not None else -1),
        -(item.get("publication_year") or 0),
        str(item.get("title") or "").casefold(),
    )


def _aggregate_grants(publication_items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    aggregated: dict[str, dict[str, Any]] = {}
    for item in publication_items:
        grants = item.get("grants")
        if not isinstance(grants, list):
            continue
        for grant in grants:
            if not isinstance(grant, dict):
                continue
            award_id = str(grant.get("award_id") or grant.get("grant_number") or "").strip()
            provider = str(grant.get("provider") or "").strip().lower() or None
            if not award_id:
                continue
            key = f"{provider or '_'}|{award_id.casefold()}"
            current = aggregated.get(key)
            if current is None:
                aggregated[key] = {
                    "award_id": award_id,
                    "funder_name": grant.get("funder_name") or grant.get("funder"),
                    "provider": provider,
                    "verified": bool(grant.get("verified")),
                    "publication_count": 1,
                }
                continue
            current["publication_count"] += 1
            if grant.get("verified"):
                current["verified"] = True
            if not current.get("funder_name") and (
                grant.get("funder_name") or grant.get("funder")
            ):
                current["funder_name"] = grant.get("funder_name") or grant.get("funder")

    return sorted(
        aggregated.values(),
        key=lambda row: (
            -(row.get("publication_count") or 0),
            str(row.get("award_id") or "").casefold(),
            str(row.get("provider") or ""),
        ),
    )


def _serialize_publication(item: dict[str, Any]) -> dict[str, Any]:
    citations_by_provider = item.get("citations_by_provider")
    if not isinstance(citations_by_provider, dict):
        citations_by_provider = {}
    return {
        "id": str(item.get("id") or item.get("canonical_work_id") or ""),
        "title": item.get("title"),
        "publication_year": item.get("publication_year"),
        "journal": item.get("journal") or item.get("primary_source"),
        "citation_count": item.get("citation_count"),
        "citations_by_provider": {
            str(key): int(value)
            for key, value in citations_by_provider.items()
            if value is not None
        },
        "providers": list(item.get("providers") or []),
        "doi": item.get("doi"),
        "url": item.get("url"),
        "grants": list(item.get("grants") or []) if isinstance(item.get("grants"), list) else [],
    }


async def get_author_details(
    session: AsyncSession | None,
    canonical_author_id: str,
) -> dict[str, Any]:
    """Local-first author profile page data.

    Reuses summary/enrichment identity fields and only reads already-stored works
    for grants and publication previews (no provider crawl, no name matching).
    """
    summary = await get_author_summary(session, canonical_author_id)

    publication_items: list[dict[str, Any]] = []
    try:
        insights = AuthorInsightsService(session)
        membership = await insights._load_work_membership([str(summary["id"])])
        stored = await insights._load_stored_work_insights(set(membership.keys()))
        publication_items = [work.as_publication_item() for work in stored.values()]
    except Exception:
        # Details page should still render identity/metrics when corpus load fails.
        publication_items = []

    ranked = sorted(publication_items, key=_publication_sort_key)
    preview = [_serialize_publication(item) for item in ranked[:PUBLICATION_PREVIEW_LIMIT]]

    return {
        **summary,
        "grants": _aggregate_grants(publication_items),
        "publications": preview,
        "stored_publication_count": len(publication_items),
    }
