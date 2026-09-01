"""Schemas for grant-number suggestions and grant publications."""

from __future__ import annotations

import json
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator

from app.schemas.analysis import PublicationFacets, PublicationTimeline


class GrantSuggestionItem(BaseModel):
    grant_number: str
    normalized_grant_number: str
    funder_name: str | None = None
    provider: str
    verified: bool = False
    publication_count: int | None = None


class GrantSuggestionsResponse(BaseModel):
    items: list[GrantSuggestionItem] = Field(default_factory=list)


class GrantPublicationGrant(BaseModel):
    grant_number: str | None = None
    normalized_grant_number: str | None = None
    award_id: str | None = None
    funder: str | None = None
    funder_name: str | None = None
    agency: str | None = None
    is_searched_grant: bool = False
    verified: bool = False
    match_type: str | None = None
    provider: str | None = None


class GrantWorkAuthorProviderIds(BaseModel):
    openalex: list[str] = Field(default_factory=list)
    orcid: list[str] = Field(default_factory=list)
    arxiv: list[str] = Field(default_factory=list)


class GrantWorkAuthor(BaseModel):
    id: str | None = None
    name: str | None = None
    display_name: str | None = None
    canonical_author_id: str | None = None
    provider_ids: GrantWorkAuthorProviderIds = Field(
        default_factory=GrantWorkAuthorProviderIds
    )
    unresolved: bool = False
    institutions: list[dict[str, Any]] = Field(default_factory=list)
    institution_ids: list[str] = Field(default_factory=list)
    countries: list[str] = Field(default_factory=list)
    department: str | None = None
    raw_affiliation_text: str | None = None
    affiliation_source: str | None = None
    affiliation_confidence: float | None = None
    provider: str | None = None


class GrantPublicationFilters(BaseModel):
    from_year: int | None = Field(None, ge=1000, le=2100)
    to_year: int | None = Field(None, ge=1000, le=2100)
    sources: list[str] = Field(default_factory=list)
    institutions: list[str] = Field(default_factory=list)
    venues: list[str] = Field(default_factory=list)
    authors: list[str] = Field(default_factory=list)

    @field_validator("sources", "institutions", "venues", "authors", mode="before")
    @classmethod
    def _coerce_list(cls, value: Any) -> list[str]:
        if value is None:
            return []
        if isinstance(value, str):
            text = value.strip()
            return [text] if text else []
        if isinstance(value, list):
            return [str(item).strip() for item in value if str(item).strip()]
        return []


class GrantPublicationItem(BaseModel):
    id: str
    result_id: str | None = None
    canonical_work_id: str | None = None
    result_type: Literal["work"] = "work"
    title: str
    authors: list[GrantWorkAuthor] = Field(default_factory=list)
    publication_year: int | None = None
    journal: str | None = None
    primary_source: str | None = None
    citation_count: int | None = None
    cited_by_count: int | None = None
    doi: str | None = None
    url: str | None = None
    providers: list[str] = Field(default_factory=list)
    grants: list[GrantPublicationGrant] = Field(default_factory=list)
    source: str | None = None
    openalex_id: str | None = None
    source_id: str | None = None
    categories: list[str] = Field(default_factory=list)
    pdf_url: str | None = None
    entry_url: str | None = None
    is_open_access: bool | None = None
    work_type: str | None = None
    matched_grant_number: str | None = None
    grant_match: dict[str, Any] | None = None
    source_records: list[dict[str, Any]] = Field(default_factory=list)


class GrantPublicationsPagination(BaseModel):
    next_cursor: str | None = None
    has_more: bool = False


class GrantPublicationsResponse(BaseModel):
    grant_number: str
    normalized_grant_number: str
    provider: str
    funder_name: str | None = None
    verified: bool = False
    match_type: str | None = None
    items: list[GrantPublicationItem] = Field(default_factory=list)
    timeline: PublicationTimeline | None = None
    facets: PublicationFacets = Field(default_factory=PublicationFacets)
    pagination: GrantPublicationsPagination = Field(
        default_factory=GrantPublicationsPagination
    )


PublicationSortBy = Literal["year", "citations", "title", "venue", "author_count"]
PublicationSortDirection = Literal["asc", "desc"]


class GrantPublicationFacetSearchResponse(BaseModel):
    items: list[dict[str, Any]] = Field(default_factory=list)


class GrantPublicationsExportRequest(BaseModel):
    """Export the full filtered grant publication set (no pagination)."""

    provider: str = Field(..., description="openalex or arxiv")
    filters: GrantPublicationFilters | None = None

    @field_validator("provider")
    @classmethod
    def _normalize_provider(cls, value: str) -> str:
        text = str(value or "").strip().lower()
        if text not in {"openalex", "arxiv"}:
            raise ValueError("Provider must be openalex or arxiv.")
        return text


def parse_filters_query(raw: str | None) -> dict[str, Any] | None:
    if raw is None or not str(raw).strip():
        return None
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ValueError("filters must be a JSON object.") from exc
    if payload is None:
        return None
    if not isinstance(payload, dict):
        raise ValueError("filters must be a JSON object.")
    return GrantPublicationFilters.model_validate(payload).model_dump(exclude_none=True)
