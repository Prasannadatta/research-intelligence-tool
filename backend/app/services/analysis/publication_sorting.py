"""Shared publication result sorting before pagination."""

from __future__ import annotations

from functools import cmp_to_key
from typing import Any, Literal

PublicationSortBy = Literal["year", "citations", "title", "venue", "author_count"]
PublicationSortDirection = Literal["asc", "desc"]

SUPPORTED_PUBLICATION_SORT_FIELDS = {
    "year",
    "citations",
    "title",
    "venue",
    "author_count",
}
SUPPORTED_PUBLICATION_SORT_DIRECTIONS = {"asc", "desc"}


def normalize_publication_sort(
    sort_by: str | None,
    sort_direction: str | None,
) -> tuple[str | None, str]:
    field = str(sort_by or "").strip().lower()
    if field not in SUPPORTED_PUBLICATION_SORT_FIELDS:
        return None, "desc"
    direction = str(sort_direction or "desc").strip().lower()
    if direction not in SUPPORTED_PUBLICATION_SORT_DIRECTIONS:
        direction = "desc"
    return field, direction


def publication_sort_key(sort_by: str | None, sort_direction: str | None) -> str:
    field, direction = normalize_publication_sort(sort_by, sort_direction)
    if field is None:
        return "-"
    return f"{field}:{direction}"


def _int_value(value: Any) -> int | None:
    if value is None or value == "":
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _text_value(value: Any) -> str | None:
    text = " ".join(str(value or "").split()).casefold()
    return text or None


def _author_count(item: dict[str, Any]) -> int | None:
    authors = item.get("authors")
    if isinstance(authors, list):
        return len(authors)
    return None


def _value_for_sort(item: dict[str, Any], sort_by: str) -> int | str | None:
    if sort_by == "year":
        return _int_value(item.get("publication_year") or item.get("year"))
    if sort_by == "citations":
        return _int_value(item.get("citation_count") if item.get("citation_count") is not None else item.get("cited_by_count"))
    if sort_by == "title":
        return _text_value(item.get("title"))
    if sort_by == "venue":
        return _text_value(item.get("journal") or item.get("primary_source"))
    if sort_by == "author_count":
        return _author_count(item)
    return None


def sort_publications(
    items: list[dict[str, Any]],
    *,
    sort_by: str | None,
    sort_direction: str | None,
) -> list[dict[str, Any]]:
    field, direction = normalize_publication_sort(sort_by, sort_direction)
    if field is None:
        return list(items)
    descending = direction == "desc"

    def compare(left: dict[str, Any], right: dict[str, Any]) -> int:
        left_value = _value_for_sort(left, field)
        right_value = _value_for_sort(right, field)
        left_missing = left_value is None
        right_missing = right_value is None
        if left_missing and right_missing:
            return _fallback_compare(left, right)
        if left_missing:
            return 1
        if right_missing:
            return -1
        if left_value < right_value:
            return 1 if descending else -1
        if left_value > right_value:
            return -1 if descending else 1
        return _fallback_compare(left, right)

    return sorted(items, key=cmp_to_key(compare))


def _fallback_compare(left: dict[str, Any], right: dict[str, Any]) -> int:
    left_title = _text_value(left.get("title")) or ""
    right_title = _text_value(right.get("title")) or ""
    if left_title < right_title:
        return -1
    if left_title > right_title:
        return 1
    left_id = str(left.get("id") or left.get("result_id") or "")
    right_id = str(right.get("id") or right.get("result_id") or "")
    if left_id < right_id:
        return -1
    if left_id > right_id:
        return 1
    return 0
