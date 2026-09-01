"""Analysis API routes."""

from __future__ import annotations

import logging
import time
import uuid

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db_session
from app.schemas.analysis import (
    AuthorPublicationFacetsRequest,
    AuthorInsightsJobResponse,
    AuthorInsightsPublicationsRequest,
    AuthorInsightsPublicationsResponse,
    AuthorInsightsRequest,
    AuthorInsightsResponse,
    AuthorPublicationFacetSearchRequest,
    AuthorPublicationsExportRequest,
    AuthorPublicationsRequest,
    AuthorPublicationsResponse,
    PublicationGrantFacet,
    PublicationVenueFacet,
    PublicationFacets,
)
from app.services.analysis import AuthorAnalysisError, analyze_author_publications
from app.services.analysis.author_insights import (
    AuthorInsightsService,
    log_insights_timing,
)
from app.services.analysis.insights_jobs import (
    InsightsJobService,
    enqueue_insights_job,
    serialize_analysis_job,
)
from app.services.analysis.author_publications import (
    build_author_publication_facets,
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
    started = time.perf_counter()
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
            sort_by=body.sort_by,
            sort_direction=body.sort_direction,
            request_id=request_id,
        )
    except AuthorAnalysisError as exc:
        logger.info(
            "analysis_timing req=%s stage=route_publications ms=%s status=error",
            request_id,
            round((time.perf_counter() - started) * 1000, 1),
        )
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

    logger.info(
        "analysis_timing req=%s stage=route_publications ms=%s status=ok returned=%s",
        request_id,
        round((time.perf_counter() - started) * 1000, 1),
        len(result.get("items") or []),
    )
    return AuthorPublicationsResponse.model_validate(result)


@router.post(
    "/authors/publications/facets",
    response_model=PublicationFacets,
)
async def author_publication_facets(
    body: AuthorPublicationFacetsRequest,
    session: AsyncSession = Depends(get_db_session),
) -> PublicationFacets:
    started = time.perf_counter()
    logger.info(
        "analysis_timing req=facets stage=route_facets_start authors=%s",
        len(body.authors),
    )
    try:
        result = await build_author_publication_facets(
            session,
            authors=[author.model_dump() for author in body.authors],
            filters=body.filters.model_dump() if body.filters else None,
        )
    except AuthorAnalysisError as exc:
        logger.info(
            "analysis_timing req=facets stage=route_facets ms=%s status=error",
            round((time.perf_counter() - started) * 1000, 1),
        )
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc
    logger.info(
        "analysis_timing req=facets stage=route_facets ms=%s status=ok",
        round((time.perf_counter() - started) * 1000, 1),
    )
    return PublicationFacets.model_validate(result)


@router.post(
    "/authors/insights",
    response_model=AuthorInsightsResponse,
)
async def author_insights_dashboard(
    body: AuthorInsightsRequest,
    session: AsyncSession = Depends(get_db_session),
) -> AuthorInsightsResponse:
    request_started = time.perf_counter()
    author_payloads = [author.model_dump() for author in body.authors]
    try:
        result = await AuthorInsightsService(session).build_dashboard(
            authors=author_payloads,
            filters=body.filters.model_dump() if body.filters else None,
            excluded_work_ids=body.excluded_work_ids,
        )
    except AuthorAnalysisError as exc:
        log_insights_timing(
            "total_request",
            request_started,
            author_count=len(author_payloads),
            status="error",
        )
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc
    log_insights_timing(
        "total_request",
        request_started,
        author_count=len(author_payloads),
        work_count=result.get("metrics", {}).get("total_unique_publications"),
        status="ok",
    )
    return AuthorInsightsResponse.model_validate(result)


@router.post(
    "/authors/insights/jobs",
    response_model=AuthorInsightsJobResponse,
)
async def create_author_insights_job(
    body: AuthorInsightsRequest,
    session: AsyncSession = Depends(get_db_session),
) -> AuthorInsightsJobResponse:
    payload = {
        "authors": [author.model_dump() for author in body.authors],
        "filters": body.filters.model_dump() if body.filters else None,
        "excluded_work_ids": body.excluded_work_ids,
    }
    job = await enqueue_insights_job(session, payload)
    return AuthorInsightsJobResponse.model_validate(job)


@router.get(
    "/authors/insights/jobs/{job_id}",
    response_model=AuthorInsightsJobResponse,
)
async def get_author_insights_job(
    job_id: uuid.UUID,
    session: AsyncSession = Depends(get_db_session),
) -> AuthorInsightsJobResponse:
    job = await InsightsJobService(session).get_job(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Insights job not found.")
    return AuthorInsightsJobResponse.model_validate(serialize_analysis_job(job))


@router.post(
    "/authors/insights/publications",
    response_model=AuthorInsightsPublicationsResponse,
)
async def author_insights_publications(
    body: AuthorInsightsPublicationsRequest,
    session: AsyncSession = Depends(get_db_session),
) -> AuthorInsightsPublicationsResponse:
    try:
        result = await AuthorInsightsService(session).build_combination_publications(
            authors=[author.model_dump() for author in body.authors],
            combination_id=body.combination_id,
            filters=body.filters.model_dump() if body.filters else None,
            excluded_work_ids=body.excluded_work_ids,
            cursor=body.cursor,
            limit=body.limit,
        )
    except AuthorAnalysisError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc
    return AuthorInsightsPublicationsResponse.model_validate(result)


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
