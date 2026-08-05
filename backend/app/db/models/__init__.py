"""Database models package."""

from app.db.models.author_analysis import AuthorAnalysisSearch
from app.db.models.author_identity import (
    AuthorAlias,
    AuthorInstitution,
    AuthorMatchEvidence,
    AuthorWork,
    CanonicalAuthor,
    ProviderAuthorRecord,
)
from app.db.models.author_profile import AuthorProfile, CanonicalAuthorInstitution
from app.db.models.work_persistence import (
    CanonicalWork,
    ProviderSearchCache,
    ProviderWorkRecord,
    SearchSession,
    SearchSessionResult,
    WorkAuthorship,
    WorkGrantMatch,
)

__all__ = [
    "AuthorAnalysisSearch",
    "AuthorAlias",
    "AuthorInstitution",
    "AuthorMatchEvidence",
    "AuthorProfile",
    "AuthorWork",
    "CanonicalAuthor",
    "CanonicalAuthorInstitution",
    "CanonicalWork",
    "ProviderAuthorRecord",
    "ProviderSearchCache",
    "ProviderWorkRecord",
    "SearchSession",
    "SearchSessionResult",
    "WorkAuthorship",
    "WorkGrantMatch",
]
