"""Business logic for saved search definitions.

Author saved-search identity (fingerprint):
  sorted canonical author IDs + analysis mode + normalized filters

Display name is never part of the fingerprint. Author order does not matter.
Excluded work IDs and provider metadata are stored but do not affect identity.
"""

from __future__ import annotations

import hashlib
import json
import uuid
from datetime import datetime, timezone
from typing import Any, Literal

from sqlalchemy import asc, desc, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.saved_search import SavedSearch
from app.schemas.saved_searches import SavedSearchCreate, SavedSearchPatch
from app.services.analysis.publication_filters import normalize_filters as normalize_publication_filters
from app.services.saved_searches.repository import SavedSearchRepository

WriteOutcome = Literal["created", "already_exists", "updated"]


class SavedSearchError(Exception):
    def __init__(self, message: str, status_code: int = 400):
        super().__init__(message)
        self.status_code = status_code


AUTHOR_FILTER_KEYS = ("from_year", "to_year", "sources", "institutions", "venues", "grant_numbers")
GRANT_FILTER_KEYS = ("from_year", "to_year", "sources", "institutions", "venues", "authors")
SORT_COLUMNS = {
    "last_viewed_at": SavedSearch.last_viewed_at,
    "created_at": SavedSearch.created_at,
    "updated_at": SavedSearch.updated_at,
    "display_name": SavedSearch.display_name,
    "view_count": SavedSearch.view_count,
}
DUPLICATE_MESSAGE = "A saved search with this configuration already exists."


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


def analysis_mode_for_author_ids(author_ids: list[str]) -> str:
    """Derive analysis mode from the selected author set."""
    return "common_publications" if len(author_ids) > 1 else "single_author"


def normalize_saved_search_filters(filters: Any, *, search_type: str) -> dict[str, Any]:
    """Normalize filters using the shared publication filter rules, then project keys."""
    if filters is None:
        filters = {}
    if not isinstance(filters, dict):
        raise SavedSearchError("applied filters must be an object.", 422)

    full = normalize_publication_filters(filters)
    keys = AUTHOR_FILTER_KEYS if search_type == "authors" else GRANT_FILTER_KEYS
    normalized: dict[str, Any] = {}
    for key in keys:
        value = full.get(key)
        if key in {"from_year", "to_year"}:
            normalized[key] = value
        else:
            normalized[key] = sorted(value or [])
    return normalized


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


def author_fingerprint(*, author_ids: list[str], filters: dict[str, Any]) -> str:
    """Stable identity for an author saved search."""
    sorted_ids = _unique_sorted_strings(author_ids)
    definition = {
        "author_ids": sorted_ids,
        "analysis_mode": analysis_mode_for_author_ids(sorted_ids),
        "filters": filters,
    }
    return _canonical_digest("authors", definition)


def grant_fingerprint(
    *,
    grant_number: str,
    provider: str,
    filters: dict[str, Any],
) -> str:
    """Stable identity for a grant saved search."""
    definition = {
        "grant_number": grant_number,
        "provider": provider,
        "filters": filters,
    }
    return _canonical_digest("grant", definition)


def _compact_grant_number(value: Any) -> str:
    return "".join(ch for ch in _clean_string(value).lower() if ch.isalnum())


def _serialize(row: SavedSearch, *, outcome: WriteOutcome | None = None) -> dict[str, Any]:
    payload = {
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
    if outcome is not None:
        payload["outcome"] = outcome
    return payload


def _parse_author_entries(raw_authors: Any) -> list[dict[str, Any]]:
    if not isinstance(raw_authors, list) or not raw_authors:
        raise SavedSearchError("Author saved searches require a non-empty authors list.", 422)

    authors: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
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
        if canonical_author_id in seen_ids:
            continue
        seen_ids.add(canonical_author_id)
        author = {
            "canonical_author_id": canonical_author_id,
            "display_name": display_name,
        }
        for key in ("provider", "provider_author_id"):
            text = _clean_string(raw.get(key))
            if text:
                author[key] = text.lower() if key == "provider" else text
        authors.append(author)
    if not authors:
        raise SavedSearchError("Author saved searches require a non-empty authors list.", 422)
    return authors


def _selected_authors(
    authors: list[dict[str, Any]],
    active_author_ids: Any,
) -> list[dict[str, Any]]:
    """Prefer active_author_ids when present so legacy rows migrate cleanly."""
    if active_author_ids is None:
        return authors
    active = set(_unique_sorted_strings(active_author_ids))
    if not active:
        return authors
    selected = [author for author in authors if author["canonical_author_id"] in active]
    return selected or authors


class SavedSearchService:
    def __init__(self, session: AsyncSession):
        self.session = session
        self.repository = SavedSearchRepository(session)

    def _prepare_author(self, body: SavedSearchCreate) -> dict[str, Any]:
        payload = dict(body.payload)
        authors = _selected_authors(
            _parse_author_entries(payload.get("authors")),
            payload.get("active_author_ids"),
        )
        author_ids = [author["canonical_author_id"] for author in authors]
        analysis_mode = analysis_mode_for_author_ids(author_ids)
        filters = normalize_saved_search_filters(
            payload.get("filters", body.applied_filters),
            search_type="authors",
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
        if isinstance(provider_context, dict):
            provider_context = {**provider_context, "mode": analysis_mode}
        else:
            provider_context = {"mode": analysis_mode}

        normalized_payload = {
            "authors": authors,
            "active_author_ids": author_ids,
            "analysis_mode": analysis_mode,
            "filters": filters,
            "excluded_work_ids": excluded_work_ids,
            "provider_context": provider_context,
        }
        return {
            "search_type": "authors",
            "display_name": body.display_name or _display_name_for_authors(authors),
            "canonical_key": author_fingerprint(author_ids=author_ids, filters=filters),
            "payload": normalized_payload,
            "applied_filters": filters,
            "provider_context": provider_context,
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
        filters = normalize_saved_search_filters(
            payload.get("filters", body.applied_filters),
            search_type="grant",
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
        return {
            "search_type": "grant",
            "display_name": body.display_name or grant_number,
            "canonical_key": grant_fingerprint(
                grant_number=normalized_grant,
                provider=provider,
                filters=filters,
            ),
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

    def fingerprint_for_existing_row(self, row: SavedSearch) -> str:
        """Recompute fingerprint for legacy rows using current identity rules."""
        payload = row.payload or {}
        if row.search_type == "authors":
            authors = _selected_authors(
                _parse_author_entries(payload.get("authors") or []),
                payload.get("active_author_ids"),
            )
            author_ids = [author["canonical_author_id"] for author in authors]
            filters = normalize_saved_search_filters(
                payload.get("filters", row.applied_filters),
                search_type="authors",
            )
            return author_fingerprint(author_ids=author_ids, filters=filters)

        grant_number = _compact_grant_number(payload.get("grant_number"))
        provider = _clean_string(
            payload.get("provider")
            or (row.provider_context or {}).get("provider")
            or "openalex"
        ).lower()
        filters = normalize_saved_search_filters(
            payload.get("filters", row.applied_filters),
            search_type="grant",
        )
        return grant_fingerprint(
            grant_number=grant_number,
            provider=provider,
            filters=filters,
        )

    async def normalize_legacy_fingerprints(self) -> int:
        """Recompute fingerprints and collapse true duplicates. Returns rows removed."""
        rows = await self.repository.list(search_type=None, order_by=[desc(SavedSearch.updated_at)])
        by_key: dict[str, SavedSearch] = {}
        removed = 0
        for row in rows:
            try:
                new_key = self.fingerprint_for_existing_row(row)
            except SavedSearchError:
                continue
            existing = by_key.get(new_key)
            if existing is None:
                if row.canonical_key != new_key:
                    row.canonical_key = new_key
                by_key[new_key] = row
                continue
            # Keep the newest row; delete the older duplicate.
            await self.session.delete(row)
            removed += 1
        if rows:
            await self.session.commit()
        return removed

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
            await self.session.commit()
            await self.session.refresh(row)
            return _serialize(row, outcome="created")

        # Exact configuration already saved — do not create a duplicate or overwrite name.
        return _serialize(row, outcome="already_exists")

    async def lookup(self, body: SavedSearchCreate) -> dict[str, Any] | None:
        prepared = self._prepare(body)
        row = await self.repository.get_by_canonical_key(prepared["canonical_key"])
        if row is None:
            return None
        return _serialize(row)

    async def list(
        self,
        *,
        search_type: str | None,
        sort_by: str = "last_viewed_at",
        sort_direction: str = "desc",
        q: str | None = None,
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
        items = [_serialize(row) for row in rows]
        query = _clean_string(q).lower()
        if not query:
            return items
        return [item for item in items if self._matches_query(item, query)]

    @staticmethod
    def _matches_query(item: dict[str, Any], query: str) -> bool:
        if query in str(item.get("display_name") or "").lower():
            return True
        authors = (item.get("payload") or {}).get("authors") or []
        for author in authors:
            if not isinstance(author, dict):
                continue
            if query in str(author.get("display_name") or "").lower():
                return True
        grant_number = str((item.get("payload") or {}).get("grant_number") or "").lower()
        if grant_number and query in grant_number:
            return True
        return False

    async def get(self, saved_search_id: str) -> dict[str, Any]:
        row = await self.repository.get(saved_search_id)
        if row is None:
            raise SavedSearchError("Saved search not found.", 404)
        return _serialize(row)

    def _apply_author_content_updates(
        self,
        row: SavedSearch,
        *,
        authors: list[dict[str, Any]] | None,
        filters: dict[str, Any] | None,
        excluded_work_ids: list[str] | None,
    ) -> None:
        payload = dict(row.payload or {})
        next_authors = authors
        if next_authors is None:
            next_authors = _selected_authors(
                _parse_author_entries(payload.get("authors") or []),
                payload.get("active_author_ids"),
            )
        else:
            next_authors = _parse_author_entries(next_authors)

        author_ids = [author["canonical_author_id"] for author in next_authors]
        analysis_mode = analysis_mode_for_author_ids(author_ids)
        next_filters = normalize_saved_search_filters(
            filters if filters is not None else payload.get("filters", row.applied_filters),
            search_type="authors",
        )
        next_excluded = (
            _unique_sorted_strings(excluded_work_ids)
            if excluded_work_ids is not None
            else _unique_sorted_strings(payload.get("excluded_work_ids", row.excluded_work_ids))
        )
        provider_context = dict(row.provider_context or {})
        provider_context["mode"] = analysis_mode
        providers = _unique_sorted_strings(
            [author.get("provider") for author in next_authors], lower=True
        )
        if providers:
            provider_context["providers"] = providers

        row.canonical_key = author_fingerprint(author_ids=author_ids, filters=next_filters)
        row.payload = {
            "authors": next_authors,
            "active_author_ids": author_ids,
            "analysis_mode": analysis_mode,
            "filters": next_filters,
            "excluded_work_ids": next_excluded,
            "provider_context": provider_context,
        }
        row.applied_filters = next_filters
        row.provider_context = provider_context
        row.excluded_work_ids = next_excluded

    def _apply_grant_content_updates(
        self,
        row: SavedSearch,
        *,
        filters: dict[str, Any] | None,
    ) -> None:
        payload = dict(row.payload or {})
        grant_number = _clean_string(payload.get("grant_number"))
        normalized_grant = _compact_grant_number(grant_number)
        provider = _clean_string(
            payload.get("provider") or (row.provider_context or {}).get("provider") or "openalex"
        ).lower()
        next_filters = normalize_saved_search_filters(
            filters if filters is not None else payload.get("filters", row.applied_filters),
            search_type="grant",
        )
        row.canonical_key = grant_fingerprint(
            grant_number=normalized_grant,
            provider=provider,
            filters=next_filters,
        )
        row.payload = {
            "grant_number": grant_number,
            "provider": provider,
            "filters": next_filters,
        }
        row.applied_filters = next_filters

    async def patch(self, saved_search_id: str, body: SavedSearchPatch) -> dict[str, Any]:
        row = await self.repository.get(saved_search_id)
        if row is None:
            raise SavedSearchError("Saved search not found.", 404)

        updates = body.model_dump(exclude_unset=True)
        content_changed = any(key in updates for key in ("authors", "filters", "excluded_work_ids"))

        if content_changed:
            # Preview the new fingerprint before mutating the row so a conflict
            # check does not flush a duplicate canonical_key.
            preview = SavedSearch(
                id=row.id,
                search_type=row.search_type,
                display_name=row.display_name,
                canonical_key=row.canonical_key,
                payload=dict(row.payload or {}),
                applied_filters=dict(row.applied_filters or {}),
                provider_context=dict(row.provider_context or {}),
                excluded_work_ids=list(row.excluded_work_ids or []) if row.excluded_work_ids else None,
            )
            if row.search_type == "authors":
                authors = updates["authors"] if updates.get("authors") is not None else None
                self._apply_author_content_updates(
                    preview,
                    authors=authors,
                    filters=updates.get("filters") if "filters" in updates else None,
                    excluded_work_ids=(
                        updates.get("excluded_work_ids")
                        if "excluded_work_ids" in updates
                        else None
                    ),
                )
            elif row.search_type == "grant":
                if "authors" in updates:
                    raise SavedSearchError("Grant saved searches cannot replace authors.", 422)
                self._apply_grant_content_updates(
                    preview,
                    filters=updates.get("filters") if "filters" in updates else None,
                )
            else:
                raise SavedSearchError("Unsupported saved search type.", 422)

            conflict = await self.repository.get_by_canonical_key(preview.canonical_key)
            if conflict is not None and conflict.id != row.id:
                raise SavedSearchError(DUPLICATE_MESSAGE, 409)

            row.canonical_key = preview.canonical_key
            row.payload = preview.payload
            row.applied_filters = preview.applied_filters
            row.provider_context = preview.provider_context
            row.excluded_work_ids = preview.excluded_work_ids

        if "display_name" in updates:
            name = updates["display_name"]
            if name:
                row.display_name = name
            elif row.search_type == "authors":
                authors = (row.payload or {}).get("authors") or []
                row.display_name = _display_name_for_authors(authors)
            else:
                row.display_name = _clean_string((row.payload or {}).get("grant_number")) or row.display_name

        if "is_pinned" in updates and updates["is_pinned"] is not None:
            row.is_pinned = bool(updates["is_pinned"])
        if "notes" in updates:
            row.notes = updates["notes"]
        if "metadata" in updates:
            row.metadata_ = updates["metadata"]

        row.updated_at = datetime.now(timezone.utc)
        await self.session.commit()
        await self.session.refresh(row)
        return _serialize(row, outcome="updated")

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
