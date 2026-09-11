"""Author identity resolution package."""

from __future__ import annotations

from typing import Any

from app.services.author_resolution.candidate import (
    AuthorCandidate,
    candidate_from_provider_result,
)
from app.services.author_resolution.normalization import normalize_author_name

__all__ = [
    "AuthorCandidate",
    "AuthorResolutionService",
    "candidate_from_provider_result",
    "normalize_author_name",
    "resolve_author_page",
    "serialize_canonical_author",
]


def __getattr__(name: str) -> Any:
    # Lazy exports avoid circular imports with ORCID normalize helpers.
    if name in {
        "AuthorResolutionService",
        "resolve_author_page",
        "serialize_canonical_author",
    }:
        from app.services.author_resolution import service as _service

        return getattr(_service, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
