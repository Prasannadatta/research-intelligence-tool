"""Data updater API routes."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db_session
from app.schemas.data_updater import (
    DataUpdateEntityRequest,
    DataUpdateJobDetailResponse,
    DataUpdateJobResponse,
    DataUpdateRequest,
    DataUpdateSavedSearchRequest,
    DataUpdaterCategoriesResponse,
    DataUpdaterSavedSearchOptionsResponse,
    DataUpdaterSearchResponse,
)
from app.services.data_updater import DataUpdaterError, DataUpdaterService

router = APIRouter(
    prefix="/api/data-updater",
    tags=["data-updater"],
)


def _raise_error(exc: DataUpdaterError) -> None:
    raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc


def _service(session: AsyncSession) -> DataUpdaterService:
    return DataUpdaterService(session)


@router.get("/categories", response_model=DataUpdaterCategoriesResponse)
async def data_update_categories(
    session: AsyncSession = Depends(get_db_session),
) -> DataUpdaterCategoriesResponse:
    try:
        items = await _service(session).categories()
    except DataUpdaterError as exc:
        _raise_error(exc)
    return DataUpdaterCategoriesResponse(items=items)


@router.get("/search", response_model=DataUpdaterSearchResponse)
async def search_data_update_targets(
    q: str = Query("", min_length=0),
    limit: int = Query(8, ge=1, le=20),
    session: AsyncSession = Depends(get_db_session),
) -> DataUpdaterSearchResponse:
    try:
        items = await _service(session).search_targets(q, limit=limit)
    except DataUpdaterError as exc:
        _raise_error(exc)
    return DataUpdaterSearchResponse(items=items)


@router.get("/saved-searches", response_model=DataUpdaterSavedSearchOptionsResponse)
async def data_update_saved_search_options(
    session: AsyncSession = Depends(get_db_session),
) -> DataUpdaterSavedSearchOptionsResponse:
    try:
        items = await _service(session).saved_search_options()
    except DataUpdaterError as exc:
        _raise_error(exc)
    return DataUpdaterSavedSearchOptionsResponse(items=items)


@router.post("/refresh", response_model=DataUpdateJobResponse)
async def start_data_update(
    body: DataUpdateRequest,
    session: AsyncSession = Depends(get_db_session),
) -> DataUpdateJobResponse:
    try:
        job = await _service(session).start_job(body)
    except DataUpdaterError as exc:
        _raise_error(exc)
    return DataUpdateJobResponse.model_validate(job)


@router.post("/refresh/entity", response_model=DataUpdateJobResponse)
async def start_entity_data_update(
    body: DataUpdateEntityRequest,
    session: AsyncSession = Depends(get_db_session),
) -> DataUpdateJobResponse:
    try:
        job = await _service(session).start_entity_job(
            entity_type=body.type,
            entity_id=body.id,
            stale_only=body.stale_only,
        )
    except DataUpdaterError as exc:
        _raise_error(exc)
    return DataUpdateJobResponse.model_validate(job)


@router.post("/refresh/saved-search", response_model=DataUpdateJobResponse)
async def start_saved_search_data_update(
    body: DataUpdateSavedSearchRequest,
    session: AsyncSession = Depends(get_db_session),
) -> DataUpdateJobResponse:
    try:
        job = await _service(session).start_saved_search_job(
            saved_search_id=body.saved_search_id,
            stale_only=body.stale_only,
        )
    except DataUpdaterError as exc:
        _raise_error(exc)
    return DataUpdateJobResponse.model_validate(job)


@router.post("/refresh/saved-searches", response_model=DataUpdateJobResponse)
async def start_all_saved_searches_data_update(
    session: AsyncSession = Depends(get_db_session),
) -> DataUpdateJobResponse:
    try:
        job = await _service(session).start_all_saved_searches_job(stale_only=True)
    except DataUpdaterError as exc:
        _raise_error(exc)
    return DataUpdateJobResponse.model_validate(job)


@router.get("/jobs/{job_id}", response_model=DataUpdateJobDetailResponse)
async def get_data_update_job(
    job_id: str,
    include_records: bool = Query(True),
    session: AsyncSession = Depends(get_db_session),
) -> DataUpdateJobDetailResponse:
    try:
        job = await _service(session).get_job(
            job_id,
            include_records=include_records,
        )
    except DataUpdaterError as exc:
        _raise_error(exc)
    if "records" not in job:
        job["records"] = []
    return DataUpdateJobDetailResponse.model_validate(job)


@router.post("/jobs/{job_id}/pause", response_model=DataUpdateJobResponse)
async def pause_data_update_job(
    job_id: str,
    session: AsyncSession = Depends(get_db_session),
) -> DataUpdateJobResponse:
    try:
        job = await _service(session).pause_job(job_id)
    except DataUpdaterError as exc:
        _raise_error(exc)
    return DataUpdateJobResponse.model_validate(job)


@router.post("/jobs/{job_id}/resume", response_model=DataUpdateJobResponse)
async def resume_data_update_job(
    job_id: str,
    session: AsyncSession = Depends(get_db_session),
) -> DataUpdateJobResponse:
    try:
        job = await _service(session).resume_job(job_id)
    except DataUpdaterError as exc:
        _raise_error(exc)
    return DataUpdateJobResponse.model_validate(job)


@router.post("/jobs/{job_id}/cancel", response_model=DataUpdateJobResponse)
async def cancel_data_update_job(
    job_id: str,
    session: AsyncSession = Depends(get_db_session),
) -> DataUpdateJobResponse:
    try:
        job = await _service(session).cancel_job(job_id)
    except DataUpdaterError as exc:
        _raise_error(exc)
    return DataUpdateJobResponse.model_validate(job)
