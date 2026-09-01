"""Grant suggestions and exact grant publications routes."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Path, Query
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.db.session import get_db_session
from app.schemas.grants import (
    GrantPublicationFacetSearchResponse,
    GrantPublicationsExportRequest,
    GrantPublicationsResponse,
    GrantSuggestionsResponse,
    parse_filters_query,
)
from app.schemas.analysis import PublicationFacets
from app.services.analysis.publication_csv_export import (
    prepare_grant_publication_export,
    stream_publication_csv,
)
from app.services.grants import (
    build_grant_publication_facets,
    GrantPublicationsError,
    GrantSuggestionsError,
    list_grant_publications,
    search_grant_publication_authors,
    search_grant_publication_venues,
    suggest_grant_numbers,
)

router = APIRouter(
    prefix="/api/grants",
    tags=["grants"]
)


async def _optional_db_session():
    """Yield a DB session when persistence is enabled; else None."""
    settings = get_settings()
    if not settings.work_persistence_enabled:
        yield None
        return
    async for session in get_db_session():
        yield session


@router.get(
    "/suggestions",
    response_model=GrantSuggestionsResponse,
)
async def grant_suggestions(
    q: str = Query(..., min_length=1, description="Grant-number prefix"),
    provider: str = Query(..., description="openalex or arxiv"),
    limit: int = Query(10, ge=1, le=10),
    session: AsyncSession | None = Depends(_optional_db_session),
) -> GrantSuggestionsResponse:
    try:
        result = await suggest_grant_numbers(
            session,
            q=q,
            provider=provider,
            limit=limit,
        )
    except GrantSuggestionsError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc

    return GrantSuggestionsResponse.model_validate(result)


@router.get(
    "/{grant_number}/publications/facets",
    response_model=PublicationFacets,
)
async def grant_publication_facets(
    grant_number: str = Path(..., min_length=1),
    provider: str = Query(..., description="openalex or arxiv"),
    filters: str | None = Query(
        None,
        description="JSON object with from_year, to_year, sources, institutions, venues, authors",
    ),
    session: AsyncSession | None = Depends(_optional_db_session),
) -> PublicationFacets:
    try:
        parsed_filters = parse_filters_query(filters)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    try:
        result = await build_grant_publication_facets(
            session,
            grant_number=grant_number,
            provider=provider,
            filters=parsed_filters,
        )
    except GrantPublicationsError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc
    return PublicationFacets.model_validate(result)


@router.get(
    "/{grant_number}/publications/venues/search",
    response_model=GrantPublicationFacetSearchResponse,
)
async def grant_publication_venues_search(
    grant_number: str = Path(..., min_length=1),
    provider: str = Query(..., description="openalex or arxiv"),
    q: str = Query("", description="Venue search query"),
    limit: int = Query(25, ge=1, le=50),
    session: AsyncSession | None = Depends(_optional_db_session),
) -> GrantPublicationFacetSearchResponse:
    try:
        items = await search_grant_publication_venues(
            session,
            grant_number=grant_number,
            provider=provider,
            query=q,
            limit=limit,
        )
    except GrantPublicationsError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc
    return GrantPublicationFacetSearchResponse(items=items)


@router.get(
    "/{grant_number}/publications/authors/search",
    response_model=GrantPublicationFacetSearchResponse,
)
async def grant_publication_authors_search(
    grant_number: str = Path(..., min_length=1),
    provider: str = Query(..., description="openalex or arxiv"),
    q: str = Query("", description="Author search query"),
    limit: int = Query(25, ge=1, le=50),
    session: AsyncSession | None = Depends(_optional_db_session),
) -> GrantPublicationFacetSearchResponse:
    try:
        items = await search_grant_publication_authors(
            session,
            grant_number=grant_number,
            provider=provider,
            query=q,
            limit=limit,
        )
    except GrantPublicationsError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc
    return GrantPublicationFacetSearchResponse(items=items)


@router.post("/{grant_number}/publications/export")
async def grant_publications_export(
    body: GrantPublicationsExportRequest,
    grant_number: str = Path(..., min_length=1),
    session: AsyncSession | None = Depends(_optional_db_session),
) -> StreamingResponse:
    try:
        prepared = await prepare_grant_publication_export(
            session,
            grant_number=grant_number,
            provider=body.provider,
            filters=body.filters.model_dump() if body.filters else None,
        )
    except GrantPublicationsError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc

    filename = prepared["filename"]
    headers = {
        "Content-Disposition": f'attachment; filename="{filename}"',
        "Cache-Control": "no-store",
        "X-Export-Row-Count": str(prepared["row_count"]),
    }
    return StreamingResponse(
        stream_publication_csv(prepared),
        media_type="text/csv; charset=utf-8",
        headers=headers,
    )


@router.get(
    "/{grant_number}/publications",
    response_model=GrantPublicationsResponse,
)
async def grant_publications(
    grant_number: str = Path(..., min_length=1),
    provider: str = Query(..., description="openalex or arxiv"),
    cursor: str | None = Query(None),
    limit: int = Query(20, ge=1, le=20),
    sort_by: str | None = Query(
        None,
        pattern="^(year|citations|title|venue|author_count)$",
    ),
    sort_direction: str = Query("desc", pattern="^(asc|desc)$"),
    filters: str | None = Query(
        None,
        description="JSON object with from_year, to_year, sources, venues, authors",
    ),
    session: AsyncSession | None = Depends(_optional_db_session),
) -> GrantPublicationsResponse:
    try:
        parsed_filters = parse_filters_query(filters)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    try:
        result = await list_grant_publications(
            session,
            grant_number=grant_number,
            provider=provider,
            limit=limit,
            cursor=cursor,
            filters=parsed_filters,
            sort_by=sort_by,
            sort_direction=sort_direction,
        )
    except GrantPublicationsError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc

    return GrantPublicationsResponse.model_validate(result)
