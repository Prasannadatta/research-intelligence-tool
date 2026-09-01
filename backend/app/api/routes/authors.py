from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db_session
from app.schemas.author import AuthorResponse
from app.schemas.author_summary import AuthorSummaryResponse
from app.services.author_service import AuthorDataError, search_authors
from app.services.authors.summary import (
    AuthorSummaryError,
    get_author_summary,
    get_author_summary_by_openalex_id,
)

router = APIRouter(
    prefix="/api/authors",
    tags=["authors"]
)


@router.get("/search", response_model=list[AuthorResponse])
def search_authors_endpoint(
    query: str = Query(..., min_length=2, description="Author search text"),
    limit: int = Query(10, ge=1, le=25, description="Maximum number of results"),
) -> list[AuthorResponse]:
    try:
        return search_authors(query=query, limit=limit)
    except AuthorDataError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.get(
    "/by-provider/openalex/{openalex_id}/summary",
    response_model=AuthorSummaryResponse,
)
async def author_summary_by_openalex_endpoint(
    openalex_id: str,
    session: AsyncSession = Depends(get_db_session),
) -> AuthorSummaryResponse:
    try:
        result = await get_author_summary_by_openalex_id(session, openalex_id)
    except AuthorSummaryError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc
    return AuthorSummaryResponse.model_validate(result)


@router.get("/{canonical_author_id}/summary", response_model=AuthorSummaryResponse)
async def author_summary_endpoint(
    canonical_author_id: str,
    session: AsyncSession = Depends(get_db_session),
) -> AuthorSummaryResponse:
    try:
        result = await get_author_summary(session, canonical_author_id)
    except AuthorSummaryError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc
    return AuthorSummaryResponse.model_validate(result)
