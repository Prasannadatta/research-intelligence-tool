"""OpenAlex search provider."""

from __future__ import annotations

from typing import Any

from app.integrations.openalex.unified_search import unified_openalex_search
from app.services.search.base import BaseSearchProvider


class OpenAlexProvider(BaseSearchProvider):
    id = "openalex"
    label = "OpenAlex"

    @property
    def enabled(self) -> bool:
        return True

    @property
    def supported_entity_types(self) -> tuple[str, ...]:
        return ("authors", "works", "grants")

    async def _run(
        self,
        *,
        entity: str,
        query: str | None,
        cursor: str | None,
        limit: int,
        filters: dict[str, Any],
    ) -> dict[str, Any]:
        return await unified_openalex_search(
            query=query,
            entity_type=entity,
            limit=limit,
            cursor=cursor,
            institution_id=filters.get("institution_id"),
            topic_id=filters.get("topic_id"),
            search_mode=filters.get("search_mode") or "auto",
            source="openalex",
        )

    async def search_authors(
        self,
        *,
        query: str | None,
        cursor: str | None,
        limit: int,
        filters: dict[str, Any],
    ) -> dict[str, Any]:
        return await self._run(
            entity="authors",
            query=query,
            cursor=cursor,
            limit=limit,
            filters=filters,
        )

    async def search_works(
        self,
        *,
        query: str | None,
        cursor: str | None,
        limit: int,
        filters: dict[str, Any],
    ) -> dict[str, Any]:
        return await self._run(
            entity="works",
            query=query,
            cursor=cursor,
            limit=limit,
            filters=filters,
        )

    async def search_grants(
        self,
        *,
        query: str | None,
        cursor: str | None,
        limit: int,
        filters: dict[str, Any],
    ) -> dict[str, Any]:
        # Structured award-id filter → publication/work rows only.
        return await self._run(
            entity="grants",
            query=query,
            cursor=cursor,
            limit=limit,
            filters=filters,
        )
