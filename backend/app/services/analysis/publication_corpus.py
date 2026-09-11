"""Load Analyze Authors publication items from the stored verified corpus."""

from __future__ import annotations

from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.services.analysis.author_insights import AuthorInsightsService


async def load_stored_publication_filter_items(
    session: AsyncSession,
    authors: list[dict[str, Any]],
) -> dict[str, Any]:
    """Return membership-scoped publication items from stored works.

    Used by corpus stats, venue/grant suggestions, and the publications table
    when OpenAlex coverage is already verified-complete, so table / timeline /
    facets share one filtering corpus.
    """
    insights = AuthorInsightsService(session)
    selected = await insights._resolve_selected_authors(authors)
    selected_ids = [author.canonical_author_id for author in selected]
    mode = "single_author" if len(selected_ids) == 1 else "common_publications"

    membership = await insights._load_work_membership(selected_ids)
    selected_set = set(selected_ids)
    if mode == "single_author":
        matching_ids = set(membership.keys())
    else:
        matching_ids = {
            work_id
            for work_id, author_ids in membership.items()
            if selected_set.issubset(author_ids)
        }

    stored = await insights._load_stored_work_insights(matching_ids)
    filter_items = [work.as_filter_item() for work in stored.values()]
    publication_items = [work.as_publication_item() for work in stored.values()]
    return {
        "mode": mode,
        "authors": [
            {
                "canonical_author_id": author.canonical_author_id,
                "display_name": author.display_name,
            }
            for author in selected
        ],
        "filter_items": filter_items,
        "publication_items": publication_items,
        "work_ids": matching_ids,
    }
