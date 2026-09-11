"""Schemas for author publication analysis."""

from __future__ import annotations

from datetime import datetime
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
    institutions: list[str] = Field(default_factory=list)
    venues: list[str] = Field(default_factory=list)
    grant_numbers: list[str] = Field(default_factory=list)

    @field_validator("sources", "institutions", "venues", "grant_numbers", mode="before")
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
    sort_by: Literal["year", "citations", "title", "venue", "author_count"] | None = None
    sort_direction: Literal["asc", "desc"] = "desc"
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
    institutions: list[dict[str, Any]] = Field(default_factory=list)
    institution_ids: list[str] = Field(default_factory=list)
    countries: list[str] = Field(default_factory=list)
    department: str | None = None
    raw_affiliation_text: str | None = None
    affiliation_source: str | None = None
    affiliation_confidence: float | None = None
    provider: str | None = None


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


class PublicationInstitutionFacet(BaseModel):
    value: str
    label: str
    country: str | None = None
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
    institutions: list[PublicationInstitutionFacet] = Field(default_factory=list)
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
    provider_total_count: int | None = None
    unsupported: bool = False
    unsupported_reason: str | None = None


class AuthorPublicationFacetSearchRequest(BaseModel):
    authors: list[AnalysisAuthorInput] = Field(..., min_length=1)
    query: str = Field("", max_length=200)
    limit: int = Field(20, ge=1, le=50)


class AuthorPublicationFacetsRequest(BaseModel):
    authors: list[AnalysisAuthorInput] = Field(..., min_length=1)
    filters: AuthorPublicationFilters | None = None


class AuthorInsightsAuthorInput(BaseModel):
    canonical_author_id: str
    display_name: str | None = None

    @field_validator("canonical_author_id")
    @classmethod
    def _non_empty_id(cls, value: str) -> str:
        text = " ".join(str(value or "").split())
        if not text:
            raise ValueError("Field must be a non-empty string.")
        return text

    @field_validator("display_name")
    @classmethod
    def _clean_display_name(cls, value: str | None) -> str | None:
        if value is None:
            return None
        text = " ".join(str(value).split())
        return text or None


class AuthorInsightsRequest(BaseModel):
    authors: list[AuthorInsightsAuthorInput] = Field(..., min_length=1)
    filters: AuthorPublicationFilters | None = None
    excluded_work_ids: list[str] = Field(default_factory=list)


class AuthorInsightsPublicationsRequest(BaseModel):
    authors: list[AuthorInsightsAuthorInput] = Field(..., min_length=1)
    combination_id: str
    filters: AuthorPublicationFilters | None = None
    excluded_work_ids: list[str] = Field(default_factory=list)
    cursor: str | None = None
    limit: int = Field(20, ge=1, le=20)

    @field_validator("combination_id")
    @classmethod
    def _clean_combination_id(cls, value: str) -> str:
        text = " ".join(str(value or "").split())
        if not text:
            raise ValueError("Field must be a non-empty string.")
        return text


class AuthorInsightsAuthor(BaseModel):
    canonical_author_id: str
    display_name: str


class AuthorInsightsMetrics(BaseModel):
    total_unique_publications: int = 0
    multi_selected_author_publications: int = 0
    all_selected_author_publications: int = 0
    multi_institution_publications: int = 0
    total_citations: int = 0
    average_citations: float = 0


class AuthorInsightsCombination(BaseModel):
    id: str
    author_ids: list[str] = Field(default_factory=list)
    author_names: list[str] = Field(default_factory=list)
    label: str
    publication_count: int = 0
    citation_count: int = 0
    average_citations: float = 0
    institution_count: int = 0
    grant_count: int = 0


class AuthorInsightsYearBucket(BaseModel):
    year: int
    publication_count: int
    percentage_of_year_total: float = 0


class AuthorInsightsSelectedAuthorCountBucket(BaseModel):
    selected_author_count: int
    publication_count: int


class AuthorInsightsInstitutionCountBucket(BaseModel):
    institution_count: int
    publication_count: int


class AuthorInsightsParticipation(BaseModel):
    selected_author_counts: list[AuthorInsightsSelectedAuthorCountBucket] = Field(
        default_factory=list
    )
    institution_counts: list[AuthorInsightsInstitutionCountBucket] = Field(
        default_factory=list
    )


class AuthorInsightsInstitutionNode(BaseModel):
    id: str
    name: str
    country: str | None = None
    publication_count: int = 0


class AuthorInsightsInstitutionEdge(BaseModel):
    source: str
    target: str
    shared_publication_count: int = 0


class AuthorInsightsInstitutionNetwork(BaseModel):
    nodes: list[AuthorInsightsInstitutionNode] = Field(default_factory=list)
    edges: list[AuthorInsightsInstitutionEdge] = Field(default_factory=list)


class AuthorInsightsInstitutionRef(BaseModel):
    id: str
    name: str
    country: str | None = None


class AuthorInsightsInstitutionPartnership(BaseModel):
    institution_a: AuthorInsightsInstitutionRef
    institution_b: AuthorInsightsInstitutionRef
    shared_publication_count: int = 0
    selected_author_ids: list[str] = Field(default_factory=list)
    selected_author_names: list[str] = Field(default_factory=list)


class AuthorInsightsInstitutionDataQuality(BaseModel):
    total_works: int = 0
    works_with_any_institution: int = 0
    works_without_institution: int = 0
    works_with_partial_institution: int = 0
    works_with_complete_institution: int = 0
    works_with_multi_institution: int = 0


class AuthorInsightsCitationActivityBucket(BaseModel):
    year: int
    citation_count: int = 0
    cumulative_citations: int = 0
    publication_count: int = 0


class JournalMetricsPayload(BaseModel):
    citescore: float | None = None
    citescore_year: int | None = None
    sjr: float | None = None
    sjr_year: int | None = None
    snip: float | None = None
    snip_year: int | None = None
    source: str | None = "scopus"
    scopus_url: str | None = None


class AuthorInsightsTopJournal(BaseModel):
    venue: str
    publication_count: int = 0
    citation_count: int = 0
    issn: str | None = None
    journal_metrics: JournalMetricsPayload | None = None


class AuthorInsightsResponse(BaseModel):
    authors: list[AuthorInsightsAuthor] = Field(default_factory=list)
    metrics: AuthorInsightsMetrics = Field(default_factory=AuthorInsightsMetrics)
    combinations: list[AuthorInsightsCombination] = Field(default_factory=list)
    combination_mode: Literal["all_combinations", "scalable"] = "all_combinations"
    collaboration_by_year: list[AuthorInsightsYearBucket] = Field(default_factory=list)
    participation: AuthorInsightsParticipation = Field(
        default_factory=AuthorInsightsParticipation
    )
    institution_network: AuthorInsightsInstitutionNetwork = Field(
        default_factory=AuthorInsightsInstitutionNetwork
    )
    institution_partnerships: list[AuthorInsightsInstitutionPartnership] = Field(
        default_factory=list
    )
    citation_activity: list[AuthorInsightsCitationActivityBucket] = Field(
        default_factory=list
    )
    top_journals: list[AuthorInsightsTopJournal] = Field(default_factory=list)
    default_combination_id: str | None = None
    institution_data_quality: AuthorInsightsInstitutionDataQuality = Field(
        default_factory=AuthorInsightsInstitutionDataQuality
    )
    facets: PublicationFacets = Field(default_factory=PublicationFacets)
    coverage: dict[str, Any] | None = None


class AuthorInsightsPublicationsResponse(BaseModel):
    combination_id: str
    items: list[AnalysisPublicationItem] = Field(default_factory=list)
    pagination: AnalysisPagination = Field(default_factory=AnalysisPagination)


class AuthorInsightsJobResponse(BaseModel):
    job_id: str
    status: Literal["queued", "running", "completed", "failed"]
    request_payload: dict[str, Any] | None = None
    result: AuthorInsightsResponse | None = None
    progress_percent: int = 0
    progress_stage: str | None = None
    progress_detail: dict[str, Any] | None = None
    error_message: str | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None
    started_at: datetime | None = None
    completed_at: datetime | None = None


class AuthorPublicationCorpusStats(BaseModel):
    mode: Literal["single_author", "common_publications"]
    authors: list[AuthorInsightsAuthor] = Field(default_factory=list)
    timeline: PublicationTimeline | None = None
    facets: PublicationFacets = Field(default_factory=PublicationFacets)
    total_matching_publications: int = 0
    total_corpus_publications: int = 0
    corpus_complete: bool = False


class AuthorPublicationStatsJobResponse(BaseModel):
    job_id: str
    status: Literal["queued", "running", "completed", "failed"]
    request_payload: dict[str, Any] | None = None
    result: AuthorPublicationCorpusStats | None = None
    progress_percent: int = 0
    progress_stage: str | None = None
    progress_detail: dict[str, Any] | None = None
    error_message: str | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None
    started_at: datetime | None = None
    completed_at: datetime | None = None
