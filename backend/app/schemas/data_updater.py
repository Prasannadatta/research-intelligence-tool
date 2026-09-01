"""Schemas for manual data refresh jobs."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator


RefreshMode = Literal["record", "selected", "dataset", "all_stale", "saved_search", "all_saved_searches"]


class DataUpdaterCategory(BaseModel):
    key: str
    label: str
    description: str
    total_records: int = 0
    stale_records: int = 0
    refresh_interval_seconds: int | None = None
    refreshable_fields: list[str] = Field(default_factory=list)


class DataUpdaterCategoriesResponse(BaseModel):
    items: list[DataUpdaterCategory] = Field(default_factory=list)


class DataUpdaterSearchItem(BaseModel):
    id: str
    type: Literal["author", "publication", "institution"]
    title: str
    subtitle: str | None = None
    last_updated: datetime | None = None


class DataUpdaterSearchResponse(BaseModel):
    items: list[DataUpdaterSearchItem] = Field(default_factory=list)


class DataUpdaterSavedSearchOption(BaseModel):
    id: str
    name: str
    search_type: str
    updated_at: datetime


class DataUpdaterSavedSearchOptionsResponse(BaseModel):
    items: list[DataUpdaterSavedSearchOption] = Field(default_factory=list)


class DataUpdateEntityRequest(BaseModel):
    type: Literal["author", "publication", "institution"]
    id: str
    stale_only: bool = False

    @field_validator("id")
    @classmethod
    def _clean_id(cls, value: str) -> str:
        text = " ".join(str(value or "").split())
        if not text:
            raise ValueError("id is required")
        return text


class DataUpdateSavedSearchRequest(BaseModel):
    saved_search_id: str
    stale_only: bool = True

    @field_validator("saved_search_id")
    @classmethod
    def _clean_saved_search_id(cls, value: str) -> str:
        text = " ".join(str(value or "").split())
        if not text:
            raise ValueError("saved_search_id is required")
        return text


class DataUpdateRequest(BaseModel):
    mode: RefreshMode
    dataset: str | None = None
    record_id: str | None = None
    record_ids: list[str] = Field(default_factory=list)
    stale_only: bool = True
    run_inline: bool = False

    @field_validator("dataset", "record_id")
    @classmethod
    def _clean_optional_string(cls, value: str | None) -> str | None:
        if value is None:
            return None
        text = " ".join(str(value).split())
        return text or None

    @field_validator("record_ids", mode="before")
    @classmethod
    def _coerce_record_ids(cls, value: Any) -> list[str]:
        if value is None:
            return []
        values = value if isinstance(value, list) else [value]
        out: list[str] = []
        seen: set[str] = set()
        for item in values:
            text = " ".join(str(item or "").split())
            if not text or text in seen:
                continue
            seen.add(text)
            out.append(text)
        return out


class DataUpdateJobResponse(BaseModel):
    id: str
    mode: str
    dataset: str | None = None
    status: str
    current_dataset: str | None = None
    total_records: int
    processed_records: int
    updated_count: int
    unchanged_count: int
    retrying_count: int
    failed_count: int
    requested_record_ids: list[str] | None = None
    metadata: dict[str, Any] | None = None
    error: str | None = None
    created_at: datetime
    updated_at: datetime
    started_at: datetime | None = None
    completed_at: datetime | None = None


class DataUpdateJobRecordResponse(BaseModel):
    id: str
    job_id: str
    dataset: str
    record_id: str
    source: str | None = None
    status: str
    message: str | None = None
    retry_count: int
    created_at: datetime
    updated_at: datetime


class DataUpdateJobDetailResponse(DataUpdateJobResponse):
    records: list[DataUpdateJobRecordResponse] = Field(default_factory=list)
