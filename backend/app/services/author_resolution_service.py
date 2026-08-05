"""Author resolution service entrypoint (stable import path)."""

from app.services.author_resolution.service import (
    AuthorResolutionService,
    resolve_author_page,
    serialize_canonical_author,
)

__all__ = [
    "AuthorResolutionService",
    "resolve_author_page",
    "serialize_canonical_author",
]
