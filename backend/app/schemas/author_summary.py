"""Schemas for canonical author summary responses."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field


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


class AuthorSummaryResponse(BaseModel):
    id: str
    display_name: str
    aliases: list[str] = Field(default_factory=list)
    institutions: list[AuthorInstitutionSummary] = Field(default_factory=list)
    orcid: str | None = None
    topics: list[str] = Field(default_factory=list)
    works_count: int | None = None
    citation_count: int | None = None
    h_index: int | None = None
    providers: list[str] = Field(default_factory=list)
    updated_at: datetime | None = None
    unresolved: bool = False
