from pydantic import BaseModel, Field


class ResearcherInstitution(BaseModel):
    id: str | None = None
    name: str | None = None
    country_code: str | None = None
    type: str | None = None
    relationship: str | None = None


class ResearcherTopic(BaseModel):
    id: str | None = None
    name: str | None = None
    score: float | None = None


class ResearcherAutocompleteCandidate(BaseModel):
    candidate_id: str
    openalex_id: str
    display_name: str
    hint: str | None = None
    orcid: str | None = None
    works_count: int | None = None
    cited_by_count: int | None = None
    source: str = "openalex"
    details_loaded: bool = False


class ResearcherCandidate(BaseModel):
    candidate_id: str
    openalex_id: str
    display_name: str
    alternative_names: list[str] = Field(default_factory=list)
    orcid: str | None = None
    primary_institution: ResearcherInstitution | None = None
    institutions: list[ResearcherInstitution] = Field(default_factory=list)
    topics: list[ResearcherTopic] = Field(default_factory=list)
    works_count: int | None = None
    cited_by_count: int | None = None
    works_api_url: str | None = None
    source: str = "openalex"
    details_loaded: bool = False
    # Optional frontend-friendly hint retained from autocomplete until details load.
    hint: str | None = None
