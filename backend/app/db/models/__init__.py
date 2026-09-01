"""Database models package."""

from app.db.models.analysis_job import AnalysisJob
from app.db.models.author_analysis import AuthorAnalysisSearch
from app.db.models.author_identity import (
    AuthorAlias,
    AuthorInstitution,
    AuthorMatchEvidence,
    AuthorWork,
    CanonicalAuthor,
    ProviderAuthorRecord,
)
from app.db.models.data_update import (
    DataUpdateJob,
    DataUpdateJobRecord,
    RefreshSubjectState,
)
from app.db.models.author_profile import AuthorProfile, CanonicalAuthorInstitution
from app.db.models.journal_metrics import JournalIssnAlias, JournalMetrics
from app.db.models.saved_search import SavedSearch
from app.db.models.scopus_cited_by import (
    ScopusCitationLink,
    ScopusCitedBySync,
    ScopusCitingWork,
)
from app.db.models.work_persistence import (
    AuthorWorkSyncState,
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
    "AuthorWorkSyncState",
    "AuthorWork",
    "AnalysisJob",
    "CanonicalAuthor",
    "CanonicalAuthorInstitution",
    "JournalIssnAlias",
    "JournalMetrics",
    "CanonicalWork",
    "DataUpdateJob",
    "DataUpdateJobRecord",
    "ProviderAuthorRecord",
    "ProviderSearchCache",
    "ProviderWorkRecord",
    "RefreshSubjectState",
    "SearchSession",
    "SearchSessionResult",
    "SavedSearch",
    "ScopusCitationLink",
    "ScopusCitedBySync",
    "ScopusCitingWork",
    "WorkAuthorship",
    "WorkGrantMatch",
]
