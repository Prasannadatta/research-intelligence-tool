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
        description="ORCID OAuth client ID for optional enrichment.",
    )
    orcid_client_secret: str | None = Field(
        default=None,
        description="ORCID OAuth client secret for optional enrichment.",
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

    @property
    def openalex_configured(self) -> bool:
        return bool(self.openalex_api_key)

    @property
    def semantic_scholar_configured(self) -> bool:
        return bool(self.semantic_scholar_api_key)

    @property
    def orcid_configured(self) -> bool:
        return bool(self.orcid_client_id and self.orcid_client_secret)

    @property
    def arxiv_configured(self) -> bool:
        return bool(self.arxiv_enabled and self.arxiv_base_url)


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
