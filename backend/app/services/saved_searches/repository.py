"""Persistence helpers for saved searches."""

from __future__ import annotations

import uuid

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.saved_search import SavedSearch


class SavedSearchRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def get(self, saved_search_id: str | uuid.UUID) -> SavedSearch | None:
        try:
            row_id = (
                saved_search_id
                if isinstance(saved_search_id, uuid.UUID)
                else uuid.UUID(str(saved_search_id))
            )
        except ValueError:
            return None
        return await self.session.get(SavedSearch, row_id)

    async def get_by_canonical_key(self, canonical_key: str) -> SavedSearch | None:
        result = await self.session.execute(
            select(SavedSearch).where(SavedSearch.canonical_key == canonical_key)
        )
        return result.scalar_one_or_none()

    async def list(
        self,
        *,
        search_type: str | None,
        order_by: list,
    ) -> list[SavedSearch]:
        stmt = select(SavedSearch)
        if search_type:
            stmt = stmt.where(SavedSearch.search_type == search_type)
        stmt = stmt.order_by(*order_by)
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def add(self, row: SavedSearch) -> SavedSearch:
        self.session.add(row)
        await self.session.flush()
        return row

    async def delete(self, saved_search_id: str | uuid.UUID) -> bool:
        try:
            row_id = (
                saved_search_id
                if isinstance(saved_search_id, uuid.UUID)
                else uuid.UUID(str(saved_search_id))
            )
        except ValueError:
            return False
        result = await self.session.execute(
            delete(SavedSearch).where(SavedSearch.id == row_id)
        )
        return bool(result.rowcount)
