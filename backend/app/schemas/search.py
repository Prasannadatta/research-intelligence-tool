from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field


EntityType = Literal["authors", "works", "grants"]
SearchMode = Literal["auto", "keywords", "grant_number"]
SearchSource = Literal["openalex", "arxiv", "orcid", "all"]


class SearchInstitution(BaseModel):
    id: str | None = None
    name: str | None = None
    country_code: str | None = None
    type: str | None = None


class SearchTopic(BaseModel):
    id: str | None = None
    name: str | None = None
    score: float | None = None


class MatchedGrant(BaseModel):
    award_id: str | None = None
    display_name: str | None = None
    funder_name: str | None = None
    openalex_id: str | None = None


class SearchAuthorResult(BaseModel):
    result_id: str
    result_type: Literal["author"] = "author"
    openalex_id: str | None = None
    display_name: str
    alternative_names: list[str] = Field(default_factory=list)
    orcid: str | None = None
    primary_institution: SearchInstitution | None = None
    topics: list[SearchTopic] = Field(default_factory=list)
    works_count: int | None = None
    cited_by_count: int | None = None
    source: str = "openalex"
    match_reason: str | None = None
    matching_funded_works_count: int | None = None
    matched_grant: MatchedGrant | None = None


class SearchAuthorNameSamplePaper(BaseModel):
    result_id: str
    title: str | None = None
    publication_year: int | None = None


class SearchAuthorNameResult(BaseModel):
    result_id: str
    result_type: Literal["author_name"] = "author_name"
    source: str = "arxiv"
    display_name: str
    is_verified_profile: bool = False
    identity_type: str = "paper_metadata_name"
    matching_papers_count: int | None = None
    sample_papers: list[SearchAuthorNameSamplePaper] = Field(default_factory=list)
    primary_institution: SearchInstitution | None = None
    topics: list[SearchTopic] = Field(default_factory=list)
    works_count: int | None = None
    cited_by_count: int | None = None
    orcid: str | None = None
    openalex_id: str | None = None


class SearchWorkAuthor(BaseModel):
    id: str | None = None
    name: str | None = None


class GrantMatch(BaseModel):
    verified: bool
    type: str


class SearchWorkResult(BaseModel):
    result_id: str
    result_type: Literal["work"] = "work"
    openalex_id: str | None = None
    source_id: str | None = None
    title: str
    summary: str | None = None
    publication_year: int | None = None
    publication_date: str | None = None
    updated_date: str | None = None
    authors: list[SearchWorkAuthor] = Field(default_factory=list)
    primary_source: str | None = None
    doi: str | None = None
    work_type: str | None = None
    cited_by_count: int | None = None
    is_open_access: bool | None = None
    categories: list[str] = Field(default_factory=list)
    pdf_url: str | None = None
    entry_url: str | None = None
    source: str = "openalex"
    match_reason: str | None = None
    matched_grant: MatchedGrant | None = None
    matched_grant_number: str | None = None
    grant_match: GrantMatch | None = None


class SearchGrantResult(BaseModel):
    result_id: str
    result_type: Literal["grant"] = "grant"
    openalex_id: str
    display_name: str | None = None
    funder_name: str | None = None
    funder_award_id: str | None = None
    funding_type: str | None = None
    amount: float | None = None
    currency: str | None = None
    start_year: int | None = None
    end_year: int | None = None
    lead_investigator: str | None = None
    funded_outputs_count: int | None = None
    source: str = "openalex"
    match_reason: str | None = None
    matched_grant: MatchedGrant | None = None


class FilterInstitutionOption(BaseModel):
    id: str
    display_name: str
    country_code: str | None = None
    type: str | None = None
    works_count: int | None = None
    source: str = "openalex"


class FilterTopicOption(BaseModel):
    id: str
    display_name: str
    description: str | None = None
    works_count: int | None = None
    source: str = "openalex"


class SearchSourceCapability(BaseModel):
    id: str
    label: str
    enabled: bool
    supported_entity_types: list[str] = Field(default_factory=list)
    experimental_entity_types: list[str] = Field(default_factory=list)


class SearchCapabilitiesResponse(BaseModel):
    default_source: str = "all"
    sources: list[SearchSourceCapability] = Field(default_factory=list)


class SearchPagination(BaseModel):
    next_cursor: str | None = None
    has_more: bool = False


class AuthorListOperation(BaseModel):
    operation: str
    author: dict[str, Any] | None = None
    canonical_author_id: str | None = None


class UnifiedSearchResponse(BaseModel):
    query: str
    entity_type: EntityType
    source: str = "openalex"
    search_mode: SearchMode | str | None = None
    results: list[Any]
    next_cursor: str | None = None
    has_more: bool = False
    items: list[AuthorListOperation] | list[Any] | None = None
    updates: list[AuthorListOperation] | list[Any] | None = None
    pagination: SearchPagination | None = None
    search_session_id: str | None = None
