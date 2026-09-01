"""ORCID public API integration."""

from app.integrations.orcid.client import (
    OrcidApiError,
    OrcidClient,
    orcid_configured,
    reset_orcid_client_state_for_tests,
    search_orcid_authors,
)
from app.integrations.orcid.normalize import (
    build_orcid_author_query,
    candidate_from_orcid_payloads,
    normalize_orcid_id,
)

__all__ = [
    "OrcidApiError",
    "OrcidClient",
    "build_orcid_author_query",
    "candidate_from_orcid_payloads",
    "normalize_orcid_id",
    "orcid_configured",
    "reset_orcid_client_state_for_tests",
    "search_orcid_authors",
]
