from fastapi import APIRouter, HTTPException, Query

from app.integrations.openalex import OpenAlexApiError
from app.integrations.openalex.filters import search_institutions, search_topics
from app.schemas.search import (
    FilterInstitutionOption,
    FilterTopicOption,
    SearchCapabilitiesResponse,
    UnifiedSearchResponse,
)
from app.services.search import (
    SearchServiceError,
    get_search_capabilities,
    run_search,
)

router = APIRouter(prefix="/api/search", tags=["search"])


@router.get("/capabilities", response_model=SearchCapabilitiesResponse)
async def search_capabilities() -> SearchCapabilitiesResponse:
    return SearchCapabilitiesResponse.model_validate(get_search_capabilities())


@router.get("/filters/institutions", response_model=list[FilterInstitutionOption])
async def lookup_institutions(
    query: str = Query(..., description="Institution search text"),
    limit: int = Query(10, ge=1, le=10, description="Maximum number of results"),
) -> list[FilterInstitutionOption]:
    cleaned_query = " ".join(query.split())
    if len(cleaned_query) < 2:
        raise HTTPException(
            status_code=422,
            detail="Query must be at least 2 characters after trimming.",
        )

    try:
        results = await search_institutions(query=cleaned_query, limit=limit)
    except OpenAlexApiError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc

    return [FilterInstitutionOption.model_validate(item) for item in results]


@router.get("/filters/topics", response_model=list[FilterTopicOption])
async def lookup_topics(
    query: str = Query(..., description="Research area / topic search text"),
    limit: int = Query(10, ge=1, le=10, description="Maximum number of results"),
) -> list[FilterTopicOption]:
    cleaned_query = " ".join(query.split())
    if len(cleaned_query) < 2:
        raise HTTPException(
            status_code=422,
            detail="Query must be at least 2 characters after trimming.",
        )

    try:
        results = await search_topics(query=cleaned_query, limit=limit)
    except OpenAlexApiError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc

    return [FilterTopicOption.model_validate(item) for item in results]


@router.get("", response_model=UnifiedSearchResponse)
async def unified_search(
    query: str | None = Query(
        None,
        description="Search text (alias: q).",
    ),
    q: str | None = Query(
        None,
        description="Alias for query.",
    ),
    entity_type: str | None = Query(
        None,
        description="Entity type: authors | works | grants (alias: entity).",
        pattern="^(authors|works|grants)$",
    ),
    entity: str | None = Query(
        None,
        description="Alias for entity_type.",
        pattern="^(authors|works|grants)$",
    ),
    source: str | None = Query(
        None,
        description="Provider id: openalex | arxiv (alias: provider). 'all' is disabled.",
        pattern="^(openalex|arxiv|all)$",
    ),
    provider: str | None = Query(
        None,
        description="Alias for source.",
        pattern="^(openalex|arxiv|all)$",
    ),
    search_mode: str = Query(
        "auto",
        description="OpenAlex authors/works only: auto | keywords | grant_number.",
        pattern="^(auto|keywords|grant_number)$",
    ),
    limit: int = Query(20, ge=1, le=20, description="Page size (max 20)"),
    cursor: str | None = Query(
        None,
        description="Opaque pagination cursor. Omit or use * for the first page.",
    ),
    institution_id: str | None = Query(
        None,
        description="OpenAlex institution ID filter (authors only), e.g. I123.",
    ),
    topic_id: str | None = Query(
        None,
        description="OpenAlex topic ID filter (authors only), e.g. T123.",
    ),
    known_author_ids: str | None = Query(
        None,
        description=(
            "Comma-separated canonical author UUIDs already shown in this search "
            "session. Used so later pages can emit replace updates instead of "
            "duplicate cards."
        ),
    ),
    search_session_id: str | None = Query(
        None,
        description=(
            "Opaque search session UUID for works/grants infinite scroll. "
            "Omit on the first page; reuse the returned id on later pages."
        ),
    ),
) -> UnifiedSearchResponse:
    resolved_query = query if query is not None else q
    resolved_entity = entity_type or entity
    resolved_provider = source or provider or "openalex"

    if not resolved_entity:
        raise HTTPException(
            status_code=422,
            detail="entity_type (or entity) is required.",
        )

    known_ids = [
        part.strip()
        for part in (known_author_ids or "").split(",")
        if part.strip()
    ]

    try:
        payload = await run_search(
            query=resolved_query,
            entity_type=resolved_entity,
            source=resolved_provider,
            limit=limit,
            cursor=cursor,
            institution_id=institution_id,
            topic_id=topic_id,
            search_mode=search_mode,
            known_author_ids=known_ids,
            search_session_id=search_session_id,
        )
    except SearchServiceError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc

    return UnifiedSearchResponse.model_validate(payload)
