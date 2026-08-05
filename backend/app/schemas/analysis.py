"""Schemas for author publication analysis."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator


class AnalysisAuthorInput(BaseModel):
    canonical_author_id: str
    provider: str
    provider_author_id: str
    display_name: str

    @field_validator("canonical_author_id", "provider", "provider_author_id", "display_name")
    @classmethod
    def _non_empty(cls, value: str) -> str:
        text = " ".join(str(value or "").split())
        if not text:
            raise ValueError("Field must be a non-empty string.")
        return text

    @field_validator("provider")
    @classmethod
    def _normalize_provider(cls, value: str) -> str:
        return value.strip().lower()


class AuthorPublicationFilters(BaseModel):
    from_year: int | None = Field(None, ge=1000, le=2100)
    to_year: int | None = Field(None, ge=1000, le=2100)
    sources: list[str] = Field(default_factory=list)
    venues: list[str] = Field(default_factory=list)
    grant_numbers: list[str] = Field(default_factory=list)

    @field_validator("sources", "venues", "grant_numbers", mode="before")
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


class AuthorPublicationsRequest(BaseModel):
    authors: list[AnalysisAuthorInput] = Field(..., min_length=1)
    original_author_ids: list[str] | None = None
    filters: AuthorPublicationFilters | None = None
    limit: int = Field(20, ge=1, le=20)
    cursor: str | None = None


class AuthorPublicationsExportRequest(BaseModel):
    """Export the full filtered author publication set (no pagination)."""

    authors: list[AnalysisAuthorInput] = Field(..., min_length=1)
    filters: AuthorPublicationFilters | None = None


class AnalysisMatch(BaseModel):
    verified: bool
    method: str


class AnalysisGrant(BaseModel):
    award_id: str | None = None
    funder_name: str | None = None
    verified: bool = False
    match_type: str | None = None
    provider: str | None = None


class AnalysisWorkAuthorProviderIds(BaseModel):
    openalex: list[str] = Field(default_factory=list)
    orcid: list[str] = Field(default_factory=list)
    arxiv: list[str] = Field(default_factory=list)


class AnalysisWorkAuthor(BaseModel):
    id: str | None = None
    name: str | None = None
    display_name: str | None = None
    canonical_author_id: str | None = None
    provider_ids: AnalysisWorkAuthorProviderIds = Field(
        default_factory=AnalysisWorkAuthorProviderIds
    )
    unresolved: bool = False


class AnalysisPublicationItem(BaseModel):
    """Canonical-work publication row for analysis results."""

    id: str
    result_id: str | None = None
    canonical_work_id: str | None = None
    result_type: Literal["work"] = "work"
    title: str
    authors: list[AnalysisWorkAuthor] = Field(default_factory=list)
    publication_year: int | None = None
    journal: str | None = None
    primary_source: str | None = None
    citation_count: int | None = None
    cited_by_count: int | None = None
    doi: str | None = None
    url: str | None = None
    providers: list[str] = Field(default_factory=list)
    grants: list[AnalysisGrant] = Field(default_factory=list)
    analysis_match: AnalysisMatch
    source: str | None = None
    openalex_id: str | None = None
    source_id: str | None = None
    categories: list[str] = Field(default_factory=list)
    pdf_url: str | None = None
    entry_url: str | None = None
    is_open_access: bool | None = None
    work_type: str | None = None
    source_records: list[dict[str, Any]] = Field(default_factory=list)


class AnalysisAuthorEcho(BaseModel):
    canonical_author_id: str
    provider: str
    provider_author_id: str
    display_name: str


class AnalysisPagination(BaseModel):
    next_cursor: str | None = None
    has_more: bool = False


class PublicationTimelineBucket(BaseModel):
    period: str
    label: str
    count: int


class PublicationTimeline(BaseModel):
    interval: Literal["month", "year"]
    total_dated_publications: int = 0
    total_matching_publications: int = 0
    items: list[PublicationTimelineBucket] = Field(default_factory=list)


class PublicationSourceFacet(BaseModel):
    value: str
    label: str
    count: int


class PublicationVenueFacet(BaseModel):
    value: str
    label: str
    count: int


class PublicationGrantFacet(BaseModel):
    grant_number: str
    funder: str | None = None
    publication_count: int


class PublicationAuthorFacet(BaseModel):
    value: str
    label: str
    count: int
    canonical_author_id: str | None = None


class PublicationFacets(BaseModel):
    sources: list[PublicationSourceFacet] = Field(default_factory=list)
    venues: list[PublicationVenueFacet] = Field(default_factory=list)
    grants: list[PublicationGrantFacet] = Field(default_factory=list)
    authors: list[PublicationAuthorFacet] = Field(default_factory=list)


class AuthorPublicationsResponse(BaseModel):
    mode: Literal["single_author", "common_publications"]
    authors: list[AnalysisAuthorEcho]
    items: list[AnalysisPublicationItem] = Field(default_factory=list)
    timeline: PublicationTimeline | None = None
    facets: PublicationFacets = Field(default_factory=PublicationFacets)
    pagination: AnalysisPagination = Field(default_factory=AnalysisPagination)
    unsupported: bool = False
    unsupported_reason: str | None = None


class AuthorPublicationFacetSearchRequest(BaseModel):
    authors: list[AnalysisAuthorInput] = Field(..., min_length=1)
    query: str = Field("", max_length=200)
    limit: int = Field(20, ge=1, le=50)
