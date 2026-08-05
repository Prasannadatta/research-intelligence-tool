"""Base search provider contract."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any


class BaseSearchProvider(ABC):
    """Single-source search provider. Never fans out to other providers."""

    id: str
    label: str

    @property
    @abstractmethod
    def enabled(self) -> bool:
        raise NotImplementedError

    @property
    @abstractmethod
    def supported_entity_types(self) -> tuple[str, ...]:
        raise NotImplementedError

    @property
    def experimental_entity_types(self) -> tuple[str, ...]:
        return ()

    def supports(self, entity: str) -> bool:
        return self.enabled and entity in self.supported_entity_types

    def to_capability_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "id": self.id,
            "label": self.label,
            "enabled": self.enabled,
            "supported_entity_types": list(self.supported_entity_types),
        }
        if self.experimental_entity_types:
            payload["experimental_entity_types"] = list(
                self.experimental_entity_types
            )
        return payload

    async def search(
        self,
        *,
        entity: str,
        query: str | None,
        cursor: str | None = None,
        limit: int = 20,
        filters: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        entity_key = (entity or "").strip().lower()
        if not self.supports(entity_key):
            raise ValueError(
                f"Provider '{self.id}' does not support entity '{entity_key}'."
            )

        method = {
            "authors": self.search_authors,
            "works": self.search_works,
            "grants": self.search_grants,
        }.get(entity_key)
        if method is None:
            raise ValueError(f"Unsupported entity '{entity_key}'.")

        return await method(
            query=query,
            cursor=cursor,
            limit=limit,
            filters=filters or {},
        )

    @abstractmethod
    async def search_authors(
        self,
        *,
        query: str | None,
        cursor: str | None,
        limit: int,
        filters: dict[str, Any],
    ) -> dict[str, Any]:
        raise NotImplementedError

    @abstractmethod
    async def search_works(
        self,
        *,
        query: str | None,
        cursor: str | None,
        limit: int,
        filters: dict[str, Any],
    ) -> dict[str, Any]:
        raise NotImplementedError

    @abstractmethod
    async def search_grants(
        self,
        *,
        query: str | None,
        cursor: str | None,
        limit: int,
        filters: dict[str, Any],
    ) -> dict[str, Any]:
        raise NotImplementedError
