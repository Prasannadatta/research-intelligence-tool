"""arXiv integration package."""

from app.integrations.arxiv.client import (
    ArxivApiError,
    build_arxiv_cursor,
    fetch_arxiv_works_by_ids,
    reset_arxiv_client_state_for_tests,
    search_arxiv_authors,
    search_arxiv_grants,
    search_arxiv_publications_by_authors,
    validate_arxiv_cursor,
)
from app.integrations.arxiv.parser import (
    extract_arxiv_id,
    normalize_arxiv_work,
    parse_arxiv_feed,
)

__all__ = [
    "ArxivApiError",
    "build_arxiv_cursor",
    "extract_arxiv_id",
    "fetch_arxiv_works_by_ids",
    "normalize_arxiv_work",
    "parse_arxiv_feed",
    "reset_arxiv_client_state_for_tests",
    "search_arxiv_authors",
    "search_arxiv_grants",
    "search_arxiv_publications_by_authors",
    "validate_arxiv_cursor",
]
