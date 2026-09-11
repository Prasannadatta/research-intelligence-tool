"""Schemas for canonical author summary responses."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


class ResolveAuthorsRequest(BaseModel):
    """Provider author rows selected from search, to resolve on selection."""

    authors: list[dict[str, Any]] = Field(default_factory=list)


class ResolveAuthorsResponse(BaseModel):
    results: list[dict[str, Any]] = Field(default_factory=list)


class AuthorInstitutionYears(BaseModel):
    from_: int | None = Field(None, alias="from")
    to: int | None = None

    model_config = {"populate_by_name": True}


class AuthorInstitutionSummary(BaseModel):
    id: str | None = None
    name: str | None = None
    department: str | None = None
    country_code: str | None = None
    current: bool = False
    years: AuthorInstitutionYears | None = None
    sources: list[str] = Field(default_factory=list)


class AuthorEnrichmentStatus(BaseModel):
    pending: list[str] = Field(default_factory=list)
    sources: dict[str, bool] = Field(default_factory=dict)
    contacted: list[str] = Field(default_factory=list)


class AuthorProviderIds(BaseModel):
    openalex: list[str] = Field(default_factory=list)
    orcid: list[str] = Field(default_factory=list)
    scopus: list[str] = Field(default_factory=list)
    arxiv: list[str] = Field(default_factory=list)


class AuthorSummaryResponse(BaseModel):
    id: str
    display_name: str
    aliases: list[str] = Field(default_factory=list)
    institutions: list[AuthorInstitutionSummary] = Field(default_factory=list)
    orcid: str | None = None
    provider_ids: AuthorProviderIds = Field(default_factory=AuthorProviderIds)
    topics: list[str] = Field(default_factory=list)
    works_count: int | None = None
    citation_count: int | None = None
    h_index: int | None = None
    providers: list[str] = Field(default_factory=list)
    updated_at: datetime | None = None
    unresolved: bool = False
    enrichment: AuthorEnrichmentStatus = Field(default_factory=AuthorEnrichmentStatus)


class AuthorDetailsGrant(BaseModel):
    award_id: str | None = None
    funder_name: str | None = None
    provider: str | None = None
    verified: bool = False
    publication_count: int = 0


class AuthorDetailsPublication(BaseModel):
    id: str
    title: str | None = None
    publication_year: int | None = None
    journal: str | None = None
    citation_count: int | None = None
    citations_by_provider: dict[str, int] = Field(default_factory=dict)
    providers: list[str] = Field(default_factory=list)
    doi: str | None = None
    url: str | None = None
    grants: list[dict[str, Any]] = Field(default_factory=list)


class AuthorDetailsResponse(AuthorSummaryResponse):
    """Author profile page payload: summary fields plus stored corpus previews."""

    grants: list[AuthorDetailsGrant] = Field(default_factory=list)
    publications: list[AuthorDetailsPublication] = Field(default_factory=list)
    stored_publication_count: int | None = None
