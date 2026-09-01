"""Author publication analysis package."""

from app.services.analysis.author_insights import AuthorInsightsService
from app.services.analysis.author_publications import (
    AuthorAnalysisError,
    analyze_author_publications,
)

__all__ = [
    "AuthorAnalysisError",
    "AuthorInsightsService",
    "analyze_author_publications",
]
