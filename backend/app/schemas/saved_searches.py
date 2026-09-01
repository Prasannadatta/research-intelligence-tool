"""Schemas for saved search definitions."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


SavedSearchType = Literal["authors", "grant"]
SavedSearchSortBy = Literal[
    "last_viewed_at",
    "created_at",
    "updated_at",
    "display_name",
    "view_count",
]
SortDirection = Literal["asc", "desc"]


class SavedSearchCreate(BaseModel):
    search_type: SavedSearchType
    display_name: str | None = Field(None, max_length=512)
    payload: dict[str, Any]
    applied_filters: dict[str, Any] | None = None
    provider_context: dict[str, Any] | None = None
    excluded_work_ids: list[str] | None = None
    notes: str | None = Field(None, max_length=4000)
    metadata: dict[str, Any] | None = None

    @field_validator("payload")
    @classmethod
    def _payload_object(cls, value: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(value, dict) or not value:
            raise ValueError("payload must be a non-empty object.")
        return value

    @field_validator("display_name", "notes")
    @classmethod
    def _clean_optional_text(cls, value: str | None) -> str | None:
        if value is None:
            return None
        text = " ".join(str(value).split())
        return text or None


class SavedSearchPatch(BaseModel):
    display_name: str | None = Field(None, max_length=512)
    is_pinned: bool | None = None
    notes: str | None = Field(None, max_length=4000)
    metadata: dict[str, Any] | None = None

    @field_validator("display_name", "notes")
    @classmethod
    def _clean_optional_text(cls, value: str | None) -> str | None:
        if value is None:
            return None
        text = " ".join(str(value).split())
        return text or None


class SavedSearchResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    search_type: SavedSearchType
    display_name: str
    canonical_key: str
    payload: dict[str, Any]
    applied_filters: dict[str, Any]
    provider_context: dict[str, Any]
    excluded_work_ids: list[str] | None = None
    created_at: datetime
    updated_at: datetime
    last_viewed_at: datetime | None = None
    view_count: int
    is_pinned: bool
    notes: str | None = None
    metadata: dict[str, Any] | None = None


class SavedSearchListResponse(BaseModel):
    items: list[SavedSearchResponse] = Field(default_factory=list)
