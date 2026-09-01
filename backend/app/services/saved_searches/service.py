"""Business logic for saved search definitions."""

from __future__ import annotations

import hashlib
import json
import uuid
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import asc, desc, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.saved_search import SavedSearch
from app.schemas.saved_searches import SavedSearchCreate, SavedSearchPatch
from app.services.saved_searches.repository import SavedSearchRepository


class SavedSearchError(Exception):
    def __init__(self, message: str, status_code: int = 400):
        super().__init__(message)
        self.status_code = status_code


AUTHOR_FILTER_KEYS = ("sources", "institutions", "venues", "grant_numbers")
GRANT_FILTER_KEYS = ("sources", "institutions", "venues", "authors")
SORT_COLUMNS = {
    "last_viewed_at": SavedSearch.last_viewed_at,
    "created_at": SavedSearch.created_at,
    "updated_at": SavedSearch.updated_at,
    "display_name": SavedSearch.display_name,
    "view_count": SavedSearch.view_count,
}


def _stable_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def _clean_string(value: Any) -> str:
    return " ".join(str(value or "").split())


def _unique_sorted_strings(values: Any, *, lower: bool = False) -> list[str]:
    if values is None:
        return []
    raw_values = values if isinstance(values, list) else [values]
    cleaned: set[str] = set()
    for value in raw_values:
        text = _clean_string(value)
        if lower:
            text = text.lower()
        if text:
            cleaned.add(text)
    return sorted(cleaned)


def _normalized_json(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(key): _normalized_json(value[key]) for key in sorted(value)}
    if isinstance(value, list):
        normalized = [_normalized_json(item) for item in value]
        return sorted(normalized, key=_stable_json)
    if isinstance(value, str):
        return _clean_string(value)
    return value


def _normalize_year(value: Any) -> int | None:
    if value is None or value == "":
        return None
    try:
        year = int(value)
    except (TypeError, ValueError):
        raise SavedSearchError("Filter years must be valid integers.", 422) from None
    if year < 1000 or year > 2100:
        raise SavedSearchError("Filter years must be between 1000 and 2100.", 422)
    return year


def _normalize_filters(filters: Any, *, search_type: str) -> dict[str, Any]:
    if filters is None:
        filters = {}
    if not isinstance(filters, dict):
        raise SavedSearchError("applied filters must be an object.", 422)

    keys = AUTHOR_FILTER_KEYS if search_type == "authors" else GRANT_FILTER_KEYS
    normalized: dict[str, Any] = {
        "from_year": _normalize_year(filters.get("from_year")),
        "to_year": _normalize_year(filters.get("to_year")),
    }
    if (
        normalized["from_year"] is not None
        and normalized["to_year"] is not None
        and normalized["from_year"] > normalized["to_year"]
    ):
        raise SavedSearchError("from_year cannot be greater than to_year.", 422)

    for key in keys:
        normalized[key] = _unique_sorted_strings(
            filters.get(key), lower=(key == "sources")
        )
    return normalized


def _compact_grant_number(value: Any) -> str:
    return "".join(ch for ch in _clean_string(value).lower() if ch.isalnum())


def _display_name_for_authors(authors: list[dict[str, Any]]) -> str:
    names = [_clean_string(author.get("display_name")) for author in authors]
    names = [name for name in names if name]
    if not names:
        raise SavedSearchError("Author saved searches require author display names.", 422)
    if len(names) <= 3:
        return " + ".join(names)
    return f"{names[0]} + {names[1]} + {len(names) - 2} more"


def _canonical_digest(search_type: str, definition: dict[str, Any]) -> str:
    digest = hashlib.sha256(_stable_json(definition).encode("utf-8")).hexdigest()
    return f"{search_type}:{digest}"


def _serialize(row: SavedSearch) -> dict[str, Any]:
    return {
        "id": str(row.id),
        "search_type": row.search_type,
        "display_name": row.display_name,
        "canonical_key": row.canonical_key,
        "payload": row.payload or {},
        "applied_filters": row.applied_filters or {},
        "provider_context": row.provider_context or {},
        "excluded_work_ids": row.excluded_work_ids,
        "created_at": row.created_at,
        "updated_at": row.updated_at,
        "last_viewed_at": row.last_viewed_at,
        "view_count": row.view_count,
        "is_pinned": row.is_pinned,
        "notes": row.notes,
        "metadata": row.metadata_,
    }


class SavedSearchService:
    def __init__(self, session: AsyncSession):
        self.session = session
        self.repository = SavedSearchRepository(session)

    def _prepare_author(self, body: SavedSearchCreate) -> dict[str, Any]:
        payload = dict(body.payload)
        raw_authors = payload.get("authors")
        if not isinstance(raw_authors, list) or not raw_authors:
            raise SavedSearchError("Author saved searches require a non-empty authors list.", 422)

        authors: list[dict[str, Any]] = []
        for raw in raw_authors:
            if not isinstance(raw, dict):
                raise SavedSearchError("Each author must be an object.", 422)
            canonical_author_id = _clean_string(raw.get("canonical_author_id"))
            display_name = _clean_string(raw.get("display_name"))
            if not canonical_author_id or not display_name:
                raise SavedSearchError(
                    "Each author requires canonical_author_id and display_name.",
                    422,
                )
            author = {
                "canonical_author_id": canonical_author_id,
                "display_name": display_name,
            }
            for key in ("provider", "provider_author_id"):
                text = _clean_string(raw.get(key))
                if text:
                    author[key] = text.lower() if key == "provider" else text
            authors.append(author)

        all_author_ids = _unique_sorted_strings(
            [author["canonical_author_id"] for author in authors]
        )
        active_ids = _unique_sorted_strings(payload.get("active_author_ids") or all_author_ids)
        filters = _normalize_filters(
            payload.get("filters", body.applied_filters), search_type="authors"
        )
        excluded_work_ids = _unique_sorted_strings(
            payload.get("excluded_work_ids", body.excluded_work_ids)
        )
        provider_context = _normalized_json(
            body.provider_context
            or payload.get("provider_context")
            or {
                "providers": _unique_sorted_strings(
                    [author.get("provider") for author in authors], lower=True
                )
            }
        )
        normalized_payload = {
            "authors": authors,
            "active_author_ids": active_ids,
            "filters": filters,
            "excluded_work_ids": excluded_work_ids,
        }
        if provider_context:
            normalized_payload["provider_context"] = provider_context
        canonical_definition = {
            "author_ids": all_author_ids,
            "active_author_ids": active_ids,
            "provider_context": provider_context,
            "filters": filters,
            "excluded_work_ids": excluded_work_ids,
        }
        return {
            "search_type": "authors",
            "display_name": body.display_name or _display_name_for_authors(authors),
            "canonical_key": _canonical_digest("authors", canonical_definition),
            "payload": normalized_payload,
            "applied_filters": filters,
            "provider_context": provider_context or {},
            "excluded_work_ids": excluded_work_ids,
            "metadata": body.metadata,
            "notes": body.notes,
        }

    def _prepare_grant(self, body: SavedSearchCreate) -> dict[str, Any]:
        payload = dict(body.payload)
        grant_number = _clean_string(payload.get("grant_number"))
        normalized_grant = _compact_grant_number(grant_number)
        if not normalized_grant:
            raise SavedSearchError("Grant saved searches require a grant_number.", 422)
        provider = _clean_string(
            payload.get("provider") or (body.provider_context or {}).get("provider") or "openalex"
        ).lower()
        if provider not in {"openalex", "arxiv"}:
            raise SavedSearchError("Provider must be openalex or arxiv.", 422)
        filters = _normalize_filters(
            payload.get("filters", body.applied_filters), search_type="grant"
        )
        provider_context = _normalized_json(body.provider_context or {"provider": provider})
        if isinstance(provider_context, dict) and "provider" not in provider_context:
            provider_context = {**provider_context, "provider": provider}
        metadata = body.metadata or payload.get("metadata")
        normalized_payload = {
            "grant_number": grant_number,
            "provider": provider,
            "filters": filters,
        }
        canonical_definition = {
            "grant_number": normalized_grant,
            "provider_context": provider_context,
            "filters": filters,
        }
        return {
            "search_type": "grant",
            "display_name": body.display_name or grant_number,
            "canonical_key": _canonical_digest("grant", canonical_definition),
            "payload": normalized_payload,
            "applied_filters": filters,
            "provider_context": provider_context or {},
            "excluded_work_ids": None,
            "metadata": metadata,
            "notes": body.notes,
        }

    def _prepare(self, body: SavedSearchCreate) -> dict[str, Any]:
        if body.search_type == "authors":
            return self._prepare_author(body)
        if body.search_type == "grant":
            return self._prepare_grant(body)
        raise SavedSearchError("Unsupported saved search type.", 422)

    async def create_or_update(self, body: SavedSearchCreate) -> dict[str, Any]:
        prepared = self._prepare(body)
        row = await self.repository.get_by_canonical_key(prepared["canonical_key"])
        if row is None:
            row = await self.repository.add(
                SavedSearch(
                    id=uuid.uuid4(),
                    search_type=prepared["search_type"],
                    display_name=prepared["display_name"],
                    canonical_key=prepared["canonical_key"],
                    payload=prepared["payload"],
                    applied_filters=prepared["applied_filters"],
                    provider_context=prepared["provider_context"],
                    excluded_work_ids=prepared["excluded_work_ids"],
                    notes=prepared["notes"],
                    metadata_=prepared["metadata"],
                )
            )
        else:
            row.display_name = prepared["display_name"]
            row.payload = prepared["payload"]
            row.applied_filters = prepared["applied_filters"]
            row.provider_context = prepared["provider_context"]
            row.excluded_work_ids = prepared["excluded_work_ids"]
            row.notes = prepared["notes"] if prepared["notes"] is not None else row.notes
            if prepared["metadata"] is not None:
                row.metadata_ = prepared["metadata"]
            row.updated_at = datetime.now(timezone.utc)
        await self.session.commit()
        await self.session.refresh(row)
        return _serialize(row)

    async def list(
        self,
        *,
        search_type: str | None,
        sort_by: str = "last_viewed_at",
        sort_direction: str = "desc",
    ) -> list[dict[str, Any]]:
        if search_type not in {None, "authors", "grant"}:
            raise SavedSearchError("type must be authors or grant.", 422)
        column = SORT_COLUMNS.get(sort_by)
        if column is None:
            raise SavedSearchError("Unsupported sort field.", 422)
        direction = asc if sort_direction == "asc" else desc
        if sort_by == "last_viewed_at":
            order_by = [
                direction(func.coalesce(SavedSearch.last_viewed_at, SavedSearch.updated_at)),
                desc(SavedSearch.updated_at),
            ]
        else:
            order_by = [direction(column), desc(SavedSearch.updated_at)]
        rows = await self.repository.list(
            search_type=search_type,
            order_by=order_by,
        )
        return [_serialize(row) for row in rows]

    async def get(self, saved_search_id: str) -> dict[str, Any]:
        row = await self.repository.get(saved_search_id)
        if row is None:
            raise SavedSearchError("Saved search not found.", 404)
        return _serialize(row)

    async def patch(self, saved_search_id: str, body: SavedSearchPatch) -> dict[str, Any]:
        row = await self.repository.get(saved_search_id)
        if row is None:
            raise SavedSearchError("Saved search not found.", 404)
        updates = body.model_dump(exclude_unset=True)
        if "display_name" in updates and updates["display_name"]:
            row.display_name = updates["display_name"]
        if "is_pinned" in updates and updates["is_pinned"] is not None:
            row.is_pinned = bool(updates["is_pinned"])
        if "notes" in updates:
            row.notes = updates["notes"]
        if "metadata" in updates:
            row.metadata_ = updates["metadata"]
        row.updated_at = datetime.now(timezone.utc)
        await self.session.commit()
        await self.session.refresh(row)
        return _serialize(row)

    async def mark_viewed(self, saved_search_id: str) -> dict[str, Any]:
        row = await self.repository.get(saved_search_id)
        if row is None:
            raise SavedSearchError("Saved search not found.", 404)
        row.last_viewed_at = datetime.now(timezone.utc)
        row.view_count = int(row.view_count or 0) + 1
        row.updated_at = datetime.now(timezone.utc)
        await self.session.commit()
        await self.session.refresh(row)
        return _serialize(row)

    async def delete(self, saved_search_id: str) -> None:
        deleted = await self.repository.delete(saved_search_id)
        if not deleted:
            raise SavedSearchError("Saved search not found.", 404)
        await self.session.commit()
