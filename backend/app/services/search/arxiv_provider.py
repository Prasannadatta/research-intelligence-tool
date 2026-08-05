"""arXiv search provider."""

from __future__ import annotations

from typing import Any

from app.core.config import get_settings
from app.integrations.arxiv.client import (
    search_arxiv_authors,
    search_arxiv_grants,
    search_arxiv_works,
)
from app.services.search.base import BaseSearchProvider


class ArxivProvider(BaseSearchProvider):
    id = "arxiv"
    label = "arXiv"

    @property
    def enabled(self) -> bool:
        return bool(get_settings().arxiv_configured)

    @property
    def supported_entity_types(self) -> tuple[str, ...]:
        if not self.enabled:
            return ()
        return ("authors", "works", "grants")

    @property
    def experimental_entity_types(self) -> tuple[str, ...]:
        return ("authors",) if self.enabled else ()

    async def search_authors(
        self,
        *,
        query: str | None,
        cursor: str | None,
        limit: int,
        filters: dict[str, Any],
    ) -> dict[str, Any]:
        return await search_arxiv_authors(
            query=query or "",
            limit=limit,
            cursor=cursor,
        )

    async def search_works(
        self,
        *,
        query: str | None,
        cursor: str | None,
        limit: int,
        filters: dict[str, Any],
    ) -> dict[str, Any]:
        return await search_arxiv_works(
            query=query or "",
            limit=limit,
            cursor=cursor,
        )

    async def search_grants(
        self,
        *,
        query: str | None,
        cursor: str | None,
        limit: int,
        filters: dict[str, Any],
    ) -> dict[str, Any]:
        # Metadata text match for grant/award numbers → publication rows only.
        return await search_arxiv_grants(
            query=query or "",
            limit=limit,
            cursor=cursor,
        )
