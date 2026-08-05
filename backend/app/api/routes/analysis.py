"""Analysis API routes."""

from __future__ import annotations

import logging
import uuid

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db_session
from app.schemas.analysis import (
    AuthorPublicationFacetSearchRequest,
    AuthorPublicationsExportRequest,
    AuthorPublicationsRequest,
    AuthorPublicationsResponse,
    PublicationGrantFacet,
    PublicationVenueFacet,
)
from app.services.analysis import AuthorAnalysisError, analyze_author_publications
from app.services.analysis.author_publications import (
    search_author_publication_grants,
    search_author_publication_venues,
)
from app.services.analysis.publication_csv_export import (
    prepare_author_publication_export,
    stream_publication_csv,
)
from app.services.analysis.search_persistence import upsert_author_analysis_search

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/analysis", tags=["analysis"])


@router.post(
    "/authors/publications",
    response_model=AuthorPublicationsResponse,
)
async def author_publications_analysis(
    body: AuthorPublicationsRequest,
    request: Request,
    session: AsyncSession = Depends(get_db_session),
) -> AuthorPublicationsResponse:
    request_id = uuid.uuid4().hex[:12]
    logger.info(
        "analysis_req=%s POST /authors/publications authors=%s cursor=%s filters=%s",
        request_id,
        len(body.authors),
        bool(body.cursor),
        bool(body.filters),
    )
    try:
        result = await analyze_author_publications(
            session,
            authors=[author.model_dump() for author in body.authors],
            limit=body.limit,
            cursor=body.cursor,
            filters=body.filters.model_dump() if body.filters else None,
            request_id=request_id,
        )
    except AuthorAnalysisError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc

    # Persist distinct combinations on successful first-page responses only.
    if body.cursor is None or body.cursor == "":
        original_ids = body.original_author_ids or [
            author.canonical_author_id for author in body.authors
        ]
        try:
            await upsert_author_analysis_search(
                session,
                original_author_ids=original_ids,
                active_authors=[author.model_dump() for author in body.authors],
                mode=result["mode"],
                result_count=len(result.get("items") or []),
            )
        except Exception:
            # upsert_author_analysis_search already logs and rolls back internally.
            pass

    if await request.is_disconnected():
        logger.info("analysis_req=%s client disconnected before response", request_id)

    return AuthorPublicationsResponse.model_validate(result)


@router.post("/authors/publications/export")
async def author_publications_export(
    body: AuthorPublicationsExportRequest,
    session: AsyncSession = Depends(get_db_session),
) -> StreamingResponse:
    try:
        prepared = await prepare_author_publication_export(
            session,
            authors=[author.model_dump() for author in body.authors],
            filters=body.filters.model_dump() if body.filters else None,
        )
    except AuthorAnalysisError as exc:
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


@router.post(
    "/authors/publications/venues/search",
    response_model=list[PublicationVenueFacet],
)
async def author_publication_venues_search(
    body: AuthorPublicationFacetSearchRequest,
    session: AsyncSession = Depends(get_db_session),
) -> list[PublicationVenueFacet]:
    try:
        results = await search_author_publication_venues(
            session,
            authors=[author.model_dump() for author in body.authors],
            query=body.query,
            limit=body.limit,
        )
    except AuthorAnalysisError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc
    return [PublicationVenueFacet.model_validate(row) for row in results]


@router.post(
    "/authors/publications/grants/search",
    response_model=list[PublicationGrantFacet],
)
async def author_publication_grants_search(
    body: AuthorPublicationFacetSearchRequest,
    session: AsyncSession = Depends(get_db_session),
) -> list[PublicationGrantFacet]:
    try:
        results = await search_author_publication_grants(
            session,
            authors=[author.model_dump() for author in body.authors],
            query=body.query,
            limit=body.limit,
        )
    except AuthorAnalysisError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc
    return [PublicationGrantFacet.model_validate(row) for row in results]
