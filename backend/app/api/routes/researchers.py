from fastapi import APIRouter, HTTPException, Path, Query

from app.integrations.openalex import (
    OpenAlexApiError,
    autocomplete_openalex_authors,
    get_openalex_author,
    search_openalex_authors,
)
from app.integrations.openalex.client import is_valid_openalex_author_id
from app.schemas.researcher import (
    ResearcherAutocompleteCandidate,
    ResearcherCandidate,
)

router = APIRouter(prefix="/api/researchers", tags=["researchers"])


@router.get("/autocomplete", response_model=list[ResearcherAutocompleteCandidate])
async def autocomplete_researchers(
    query: str = Query(..., description="Researcher name autocomplete text"),
) -> list[ResearcherAutocompleteCandidate]:
    cleaned_query = " ".join(query.split())
    if len(cleaned_query) < 3:
        raise HTTPException(
            status_code=422,
            detail="Query must be at least 3 characters after trimming.",
        )

    try:
        results = await autocomplete_openalex_authors(query=cleaned_query)
    except OpenAlexApiError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc

    return [
        ResearcherAutocompleteCandidate.model_validate(item) for item in results
    ]


@router.get("/search", response_model=list[ResearcherCandidate])
async def search_researchers(
    query: str = Query(..., description="Researcher name or search text"),
    limit: int = Query(10, ge=1, le=20, description="Maximum number of results"),
) -> list[ResearcherCandidate]:
    cleaned_query = query.strip()
    if len(cleaned_query) < 2:
        raise HTTPException(
            status_code=422,
            detail="Query must be at least 2 characters after trimming.",
        )

    try:
        results = await search_openalex_authors(query=cleaned_query, limit=limit)
    except OpenAlexApiError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc

    return [ResearcherCandidate.model_validate(item) for item in results]


@router.get("/{openalex_id}", response_model=ResearcherCandidate)
async def get_researcher(
    openalex_id: str = Path(..., description="OpenAlex author ID, e.g. A123456789"),
) -> ResearcherCandidate:
    if not is_valid_openalex_author_id(openalex_id.strip()):
        raise HTTPException(
            status_code=422,
            detail="Invalid OpenAlex author ID format. Expected A followed by digits.",
        )

    try:
        result = await get_openalex_author(openalex_id)
    except OpenAlexApiError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc

    return ResearcherCandidate.model_validate(result)
