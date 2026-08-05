"""Author identity resolution package."""

from app.services.author_resolution.candidate import (
    AuthorCandidate,
    candidate_from_provider_result,
)
from app.services.author_resolution.normalization import normalize_author_name
from app.services.author_resolution.service import (
    AuthorResolutionService,
    resolve_author_page,
    serialize_canonical_author,
)

__all__ = [
    "AuthorCandidate",
    "AuthorResolutionService",
    "candidate_from_provider_result",
    "normalize_author_name",
    "resolve_author_page",
    "serialize_canonical_author",
]
