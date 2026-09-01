from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

# backend/ (parent of app/)
_BACKEND_DIR = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    """Application settings loaded from environment variables / .env."""

    model_config = SettingsConfigDict(
        env_file=str(_BACKEND_DIR / ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # Required for live researcher search (OpenAlex).
    openalex_api_key: str | None = Field(
        default=None,
        description="OpenAlex API key; required for live researcher search.",
    )

    # Optional enrichment sources — app works when these are unset/unavailable.
    semantic_scholar_api_key: str | None = Field(
        default=None,
        description="Semantic Scholar API key for optional enrichment.",
    )
    orcid_client_id: str | None = Field(
        default=None,
        description="ORCID OAuth client ID for optional enrichment (unused for public API reads).",
    )
    orcid_client_secret: str | None = Field(
        default=None,
        description="ORCID OAuth client secret for optional enrichment (unused for public API reads).",
    )
    orcid_enabled: bool = Field(
        default=True,
        description="When true, the ORCID public API client may be used (not wired into live search yet).",
    )
    orcid_public_base_url: str = Field(
        default="https://pub.orcid.org/v3.0",
        description="ORCID public API v3.0 base URL.",
    )
    orcid_user_agent: str = Field(
        default=(
            "ResearchIntelligencePlatform/0.1 "
            "mailto:research-intelligence@berkeley.edu"
        ),
        description="Descriptive User-Agent for ORCID public API requests.",
    )

    researcher_search_enrichment_enabled: bool = Field(
        default=True,
        description="When true, attempt optional enrichment from Semantic Scholar / ORCID.",
    )

    # arXiv Atom API (no API key required).
    arxiv_enabled: bool = Field(
        default=True,
        description="When true, arXiv is offered as a search source for works/authors.",
    )
    arxiv_base_url: str = Field(
        default="https://export.arxiv.org/api/query",
        description="arXiv Atom API base URL.",
    )
    arxiv_user_agent: str = Field(
        default=(
            "ResearchIntelligencePlatform/0.1 "
            "mailto:research-intelligence@berkeley.edu"
        ),
        description="Descriptive User-Agent for arXiv API requests.",
    )

    # Author identity / works persistence (SQLite async for local development).
    database_url: str = Field(
        default=f"sqlite+aiosqlite:///{_BACKEND_DIR / 'author_identity.db'}",
        description="Async SQLAlchemy database URL (SQLite for local development).",
    )
    author_resolution_enabled: bool = Field(
        default=True,
        description="When true, author search pages run identity resolution.",
    )
    author_auto_merge_threshold: int = Field(
        default=85,
        ge=0,
        le=100,
        description="Minimum total match score required for automatic merge.",
    )
    author_possible_duplicate_threshold: int = Field(
        default=60,
        ge=0,
        le=100,
        description="Minimum score to record a possible-duplicate pair.",
    )
    author_profile_freshness_days: int = Field(
        default=14,
        ge=1,
        le=90,
        description="Days before cached author profile metadata is refreshed from providers.",
    )

    # Works / grants persistence (canonical works, sessions, provider cache).
    work_persistence_enabled: bool = Field(
        default=True,
        description="When true, works/grants search pages persist canonical works and sessions.",
    )
    provider_search_cache_enabled: bool = Field(
        default=True,
        description="When true, provider search responses are stored as L2 cache.",
    )
    provider_search_cache_ttl_seconds: int = Field(
        default=6 * 60 * 60,
        ge=60,
        description="TTL for persistent provider search cache entries.",
    )
    search_session_ttl_seconds: int = Field(
        default=24 * 60 * 60,
        ge=60,
        description="TTL for infinite-scroll search sessions.",
    )
    author_work_sync_ttl_seconds: int = Field(
        default=18 * 60 * 60,
        ge=60,
        description="TTL before selected-author work coverage is refreshed from providers.",
    )
    external_api_default_max_retries: int = Field(
        default=3,
        ge=0,
        le=8,
        description="Maximum retry attempts for transient external API failures.",
    )
    external_api_backoff_base_seconds: float = Field(
        default=0.5,
        ge=0.0,
        description="Initial exponential backoff delay for external API retries.",
    )
    external_api_backoff_max_seconds: float = Field(
        default=30.0,
        ge=0.1,
        description="Maximum backoff delay for external API retries.",
    )
    openalex_rate_limit_min_interval_seconds: float = Field(
        default=1.0,
        ge=0.0,
        description="Minimum spacing between OpenAlex requests made by this process.",
    )
    openalex_rate_limit_concurrency: int = Field(
        default=1,
        ge=1,
        le=20,
        description="Maximum concurrent OpenAlex requests made by this process.",
    )
    arxiv_rate_limit_min_interval_seconds: float = Field(
        default=3.0,
        ge=0.0,
        description="Minimum spacing between arXiv requests made by this process.",
    )
    arxiv_rate_limit_concurrency: int = Field(
        default=1,
        ge=1,
        le=10,
        description="Maximum concurrent arXiv requests made by this process.",
    )
    orcid_rate_limit_min_interval_seconds: float = Field(
        default=0.25,
        ge=0.0,
        description="Minimum spacing between ORCID public API requests made by this process.",
    )
    orcid_rate_limit_concurrency: int = Field(
        default=1,
        ge=1,
        le=4,
        description="Maximum concurrent ORCID public API requests made by this process.",
    )

    # Elsevier / Scopus Serial Title API (optional journal-metrics enrichment).
    elsevier_api_key: str | None = Field(
        default=None,
        description="Elsevier API key for Scopus Serial Title journal metrics.",
    )
    elsevier_inst_token: str | None = Field(
        default=None,
        description=(
            "Optional Elsevier institutional token for remote/off-campus access. "
            "Not required when the API key's entitlement or IP access is sufficient."
        ),
    )
    elsevier_serial_title_base_url: str = Field(
        default="https://api.elsevier.com/content/serial/title",
        description="Elsevier Serial Title API base URL.",
    )
    elsevier_api_base_url: str = Field(
        default="https://api.elsevier.com",
        description="Elsevier API host for Abstract Retrieval and Scopus Search.",
    )
    elsevier_rate_limit_min_interval_seconds: float = Field(
        default=0.25,
        ge=0.0,
        description="Minimum spacing between Elsevier Serial Title requests.",
    )
    elsevier_rate_limit_concurrency: int = Field(
        default=4,
        ge=1,
        le=8,
        description="Maximum concurrent Elsevier Serial Title requests.",
    )
    journal_metrics_success_ttl_days: int = Field(
        default=60,
        ge=1,
        le=365,
        description="Days before a successful Scopus journal-metrics cache row is refreshed.",
    )
    journal_metrics_negative_ttl_days: int = Field(
        default=14,
        ge=1,
        le=90,
        description="Days to reuse not_found/unavailable journal-metrics cache rows.",
    )
    journal_metrics_enrichment_timeout_seconds: float = Field(
        default=8.0,
        ge=0.5,
        le=30.0,
        description="Maximum time Insights may spend enriching missing journal metrics.",
    )
    scopus_cited_by_success_ttl_days: int = Field(
        default=7,
        ge=1,
        le=90,
        description="Days before a successful Scopus cited-by cache is refreshed.",
    )
    scopus_cited_by_negative_ttl_days: int = Field(
        default=14,
        ge=1,
        le=90,
        description="Days to reuse not_found/unavailable Scopus cited-by cache rows.",
    )
    scopus_cited_by_page_size: int = Field(
        default=25,
        ge=1,
        le=25,
        description="Scopus Search page size for REF cited-by queries.",
    )
    scopus_cited_by_max_results: int = Field(
        default=2000,
        ge=25,
        le=10000,
        description="Maximum citing works fetched per canonical work.",
    )
    scopus_cited_by_concurrency: int = Field(
        default=1,
        ge=1,
        le=1,
        description="Maximum concurrent canonical-work cited-by syncs (SQLite-safe).",
    )
    insights_job_max_concurrency: int = Field(
        default=2,
        ge=1,
        le=2,
        description="Maximum concurrent Collaboration Insights background jobs (SQLite-safe).",
    )
    data_updater_author_profile_ttl_seconds: int = Field(
        default=14 * 24 * 60 * 60,
        ge=60,
        description="Freshness interval for author profile metadata.",
    )
    data_updater_affiliation_ttl_seconds: int = Field(
        default=30 * 24 * 60 * 60,
        ge=60,
        description="Freshness interval for author and institution affiliation data.",
    )
    data_updater_author_publications_ttl_seconds: int = Field(
        default=18 * 60 * 60,
        ge=60,
        description="Freshness interval for author publication lists.",
    )
    data_updater_publication_metadata_ttl_seconds: int = Field(
        default=30 * 24 * 60 * 60,
        ge=60,
        description="Freshness interval for publication metadata.",
    )
    data_updater_citation_counts_ttl_seconds: int = Field(
        default=24 * 60 * 60,
        ge=60,
        description="Freshness interval for citation counts.",
    )
    data_updater_grant_info_ttl_seconds: int = Field(
        default=7 * 24 * 60 * 60,
        ge=60,
        description="Freshness interval for grant and funding metadata.",
    )

    @property
    def openalex_configured(self) -> bool:
        return bool(self.openalex_api_key)

    @property
    def semantic_scholar_configured(self) -> bool:
        return bool(self.semantic_scholar_api_key)

    @property
    def orcid_oauth_configured(self) -> bool:
        return bool(self.orcid_client_id and self.orcid_client_secret)

    @property
    def orcid_configured(self) -> bool:
        return bool(self.orcid_enabled and (self.orcid_public_base_url or "").strip())

    @property
    def arxiv_configured(self) -> bool:
        return bool(self.arxiv_enabled and self.arxiv_base_url)

    @property
    def elsevier_configured(self) -> bool:
        return bool((self.elsevier_api_key or "").strip())


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
