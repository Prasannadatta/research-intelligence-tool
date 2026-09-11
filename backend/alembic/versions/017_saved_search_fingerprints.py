"""Recompute saved-search fingerprints under the authors+mode+filters identity rules."""

from __future__ import annotations

import hashlib
import json
from typing import Any

import sqlalchemy as sa
from alembic import op
from sqlalchemy import inspect

revision = "017_saved_search_fingerprints"
down_revision = "016_sync_resume_cursor"
branch_labels = None
depends_on = None


def _stable_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def _clean_string(value: Any) -> str:
    return " ".join(str(value or "").split())


def _unique_sorted_strings(values: Any) -> list[str]:
    if values is None:
        return []
    raw = values if isinstance(values, list) else [values]
    cleaned = {_clean_string(value) for value in raw if _clean_string(value)}
    return sorted(cleaned)


def _compact_grant_number(value: Any) -> str:
    return "".join(ch for ch in _clean_string(value).lower() if ch.isalnum())


def _digest(search_type: str, definition: dict[str, Any]) -> str:
    digest = hashlib.sha256(_stable_json(definition).encode("utf-8")).hexdigest()
    return f"{search_type}:{digest}"


def _normalize_filters(filters: Any, *, search_type: str) -> dict[str, Any]:
    raw = filters if isinstance(filters, dict) else {}
    keys = (
        ("from_year", "to_year", "sources", "institutions", "venues", "grant_numbers")
        if search_type == "authors"
        else ("from_year", "to_year", "sources", "institutions", "venues", "authors")
    )
    normalized: dict[str, Any] = {}
    for key in keys:
        value = raw.get(key)
        if key in {"from_year", "to_year"}:
            try:
                normalized[key] = int(value) if value is not None and value != "" else None
            except (TypeError, ValueError):
                normalized[key] = None
        else:
            items = value if isinstance(value, list) else []
            cleaned = []
            seen = set()
            for item in items:
                text = _clean_string(item)
                if key == "sources":
                    text = text.lower()
                if text and text not in seen:
                    seen.add(text)
                    cleaned.append(text)
            normalized[key] = sorted(cleaned)
    from_year = normalized.get("from_year")
    to_year = normalized.get("to_year")
    if from_year is not None and to_year is not None and from_year > to_year:
        normalized["from_year"], normalized["to_year"] = to_year, from_year
    return normalized


def _author_key(payload: dict[str, Any], applied_filters: Any) -> str | None:
    authors = payload.get("authors") if isinstance(payload.get("authors"), list) else []
    parsed = []
    for raw in authors:
        if not isinstance(raw, dict):
            continue
        author_id = _clean_string(raw.get("canonical_author_id"))
        if author_id:
            parsed.append(author_id)
    active = _unique_sorted_strings(payload.get("active_author_ids"))
    author_ids = active if active else _unique_sorted_strings(parsed)
    if not author_ids:
        return None
    filters = _normalize_filters(
        payload.get("filters", applied_filters),
        search_type="authors",
    )
    mode = "common_publications" if len(author_ids) > 1 else "single_author"
    return _digest(
        "authors",
        {
            "author_ids": author_ids,
            "analysis_mode": mode,
            "filters": filters,
        },
    )


def _grant_key(payload: dict[str, Any], applied_filters: Any, provider_context: Any) -> str | None:
    grant_number = _compact_grant_number(payload.get("grant_number"))
    if not grant_number:
        return None
    provider = _clean_string(
        payload.get("provider")
        or (provider_context or {}).get("provider")
        or "openalex"
    ).lower()
    filters = _normalize_filters(
        payload.get("filters", applied_filters),
        search_type="grant",
    )
    return _digest(
        "grant",
        {
            "grant_number": grant_number,
            "provider": provider,
            "filters": filters,
        },
    )


def upgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)
    if "saved_searches" not in inspector.get_table_names():
        return

    rows = bind.execute(
        sa.text(
            "SELECT id, search_type, canonical_key, payload, applied_filters, provider_context, updated_at "
            "FROM saved_searches"
        )
    ).mappings().all()

    by_key: dict[str, dict[str, Any]] = {}
    for row in rows:
        payload = row["payload"] if isinstance(row["payload"], dict) else {}
        if isinstance(payload, str):
            try:
                payload = json.loads(payload)
            except json.JSONDecodeError:
                payload = {}
        applied = row["applied_filters"] if isinstance(row["applied_filters"], dict) else {}
        if isinstance(applied, str):
            try:
                applied = json.loads(applied)
            except json.JSONDecodeError:
                applied = {}
        provider_context = row["provider_context"] if isinstance(row["provider_context"], dict) else {}
        if isinstance(provider_context, str):
            try:
                provider_context = json.loads(provider_context)
            except json.JSONDecodeError:
                provider_context = {}

        if row["search_type"] == "authors":
            new_key = _author_key(payload, applied)
        elif row["search_type"] == "grant":
            new_key = _grant_key(payload, applied, provider_context)
        else:
            continue
        if not new_key:
            continue

        existing = by_key.get(new_key)
        if existing is None:
            by_key[new_key] = dict(row)
            if row["canonical_key"] != new_key:
                bind.execute(
                    sa.text("UPDATE saved_searches SET canonical_key = :key WHERE id = :id"),
                    {"key": new_key, "id": row["id"]},
                )
            continue

        # Keep the newest row; drop the older duplicate.
        keep = existing
        drop = row
        keep_updated = keep.get("updated_at")
        drop_updated = drop.get("updated_at")
        if drop_updated and (not keep_updated or drop_updated > keep_updated):
            bind.execute(sa.text("DELETE FROM saved_searches WHERE id = :id"), {"id": keep["id"]})
            by_key[new_key] = dict(drop)
            if drop["canonical_key"] != new_key:
                bind.execute(
                    sa.text("UPDATE saved_searches SET canonical_key = :key WHERE id = :id"),
                    {"key": new_key, "id": drop["id"]},
                )
        else:
            bind.execute(sa.text("DELETE FROM saved_searches WHERE id = :id"), {"id": drop["id"]})


def downgrade() -> None:
    # Fingerprints are derived; rolling back identity rules is not lossless.
    return
