from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db_session
from app.schemas.author_summary import (
    AuthorDetailsResponse,
    AuthorSummaryResponse,
    ResolveAuthorsRequest,
    ResolveAuthorsResponse,
)
from app.services.authors.details import get_author_details
from app.services.authors.resolve import resolve_selected_authors
from app.services.authors.summary import (
    AuthorSummaryError,
    enrich_author_summary,
    get_author_summary,
    get_author_summary_by_openalex_id,
)

router = APIRouter(
    prefix="/api/authors",
    tags=["authors"]
)


@router.post("/resolve", response_model=ResolveAuthorsResponse)
async def resolve_authors_endpoint(
    body: ResolveAuthorsRequest,
) -> ResolveAuthorsResponse:
    """Resolve selected search hits into canonical author identity records.

    Called on selection — not during typeahead — to avoid DB writes on every keystroke.
    """
    results = await resolve_selected_authors(list(body.authors or []))
    return ResolveAuthorsResponse(results=results)


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


@router.get("/{canonical_author_id}/details", response_model=AuthorDetailsResponse)
async def author_details_endpoint(
    canonical_author_id: str,
    session: AsyncSession = Depends(get_db_session),
) -> AuthorDetailsResponse:
    """Author profile page: local summary plus stored grants/publication previews."""
    try:
        result = await get_author_details(session, canonical_author_id)
    except AuthorSummaryError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc
    return AuthorDetailsResponse.model_validate(result)


@router.post("/{canonical_author_id}/summary/enrich", response_model=AuthorSummaryResponse)
async def author_summary_enrich_endpoint(
    canonical_author_id: str,
    session: AsyncSession = Depends(get_db_session),
) -> AuthorSummaryResponse:
    """Lazy ORCID/Scopus (+ stale OpenAlex) enrichment for hover cards."""
    try:
        result = await enrich_author_summary(session, canonical_author_id)
    except AuthorSummaryError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc
    return AuthorSummaryResponse.model_validate(result)
