"""Saved search API routes."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db_session
from app.schemas.saved_searches import (
    SavedSearchCreate,
    SavedSearchListResponse,
    SavedSearchPatch,
    SavedSearchResponse,
    SavedSearchSortBy,
    SortDirection,
)
from app.services.saved_searches import SavedSearchError, SavedSearchService

router = APIRouter(prefix="/api/saved-searches", tags=["saved-searches"])


def _raise_saved_search_error(exc: SavedSearchError) -> None:
    raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc


@router.get("", response_model=SavedSearchListResponse)
async def list_saved_searches(
    type: str | None = Query(None, pattern="^(authors|grant)$"),
    sort_by: SavedSearchSortBy = "last_viewed_at",
    sort_direction: SortDirection = "desc",
    session: AsyncSession = Depends(get_db_session),
) -> SavedSearchListResponse:
    try:
        items = await SavedSearchService(session).list(
            search_type=type,
            sort_by=sort_by,
            sort_direction=sort_direction,
        )
    except SavedSearchError as exc:
        _raise_saved_search_error(exc)
    return SavedSearchListResponse(items=items)


@router.post("", response_model=SavedSearchResponse)
async def create_saved_search(
    body: SavedSearchCreate,
    session: AsyncSession = Depends(get_db_session),
) -> SavedSearchResponse:
    try:
        item = await SavedSearchService(session).create_or_update(body)
    except SavedSearchError as exc:
        _raise_saved_search_error(exc)
    return SavedSearchResponse.model_validate(item)


@router.get("/{saved_search_id}", response_model=SavedSearchResponse)
async def get_saved_search(
    saved_search_id: str,
    session: AsyncSession = Depends(get_db_session),
) -> SavedSearchResponse:
    try:
        item = await SavedSearchService(session).get(saved_search_id)
    except SavedSearchError as exc:
        _raise_saved_search_error(exc)
    return SavedSearchResponse.model_validate(item)


@router.patch("/{saved_search_id}", response_model=SavedSearchResponse)
async def patch_saved_search(
    saved_search_id: str,
    body: SavedSearchPatch,
    session: AsyncSession = Depends(get_db_session),
) -> SavedSearchResponse:
    try:
        item = await SavedSearchService(session).patch(saved_search_id, body)
    except SavedSearchError as exc:
        _raise_saved_search_error(exc)
    return SavedSearchResponse.model_validate(item)


@router.delete("/{saved_search_id}", status_code=204)
async def delete_saved_search(
    saved_search_id: str,
    session: AsyncSession = Depends(get_db_session),
) -> Response:
    try:
        await SavedSearchService(session).delete(saved_search_id)
    except SavedSearchError as exc:
        _raise_saved_search_error(exc)
    return Response(status_code=204)


@router.post("/{saved_search_id}/view", response_model=SavedSearchResponse)
async def mark_saved_search_viewed(
    saved_search_id: str,
    session: AsyncSession = Depends(get_db_session),
) -> SavedSearchResponse:
    try:
        item = await SavedSearchService(session).mark_viewed(saved_search_id)
    except SavedSearchError as exc:
        _raise_saved_search_error(exc)
    return SavedSearchResponse.model_validate(item)
