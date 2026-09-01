"""Canonical works, search sessions, provider cache, and grant provenance models."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.db.models.author_identity import GUID, JSONType


class CanonicalWork(Base):
    __tablename__ = "canonical_works"
    __table_args__ = (
        Index(
            "ix_canonical_works_title_year_author",
            "normalized_title",
            "publication_year",
            "normalized_first_author",
        ),
        Index("ix_canonical_works_doi", "doi"),
        Index("ix_canonical_works_arxiv_id", "arxiv_id"),
        Index("ix_canonical_works_pmid", "pmid"),
    )

    id: Mapped[uuid.UUID] = mapped_column(GUID(), primary_key=True, default=uuid.uuid4)
    title: Mapped[str] = mapped_column(String(1024), nullable=False)
    normalized_title: Mapped[str] = mapped_column(String(1024), nullable=False, index=True)
    publication_year: Mapped[int | None] = mapped_column(Integer, nullable=True)
    normalized_first_author: Mapped[str | None] = mapped_column(
        String(512), nullable=True
    )
    doi: Mapped[str | None] = mapped_column(String(512), nullable=True)
    arxiv_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    pmid: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    provider_records: Mapped[list[ProviderWorkRecord]] = relationship(
        back_populates="canonical_work",
        cascade="all, delete-orphan",
    )
    grant_matches: Mapped[list[WorkGrantMatch]] = relationship(
        back_populates="canonical_work",
        cascade="all, delete-orphan",
    )
    authorships: Mapped[list["WorkAuthorship"]] = relationship(
        back_populates="canonical_work",
        cascade="all, delete-orphan",
        order_by="WorkAuthorship.author_position",
    )


class ProviderWorkRecord(Base):
    __tablename__ = "provider_work_records"
    __table_args__ = (
        UniqueConstraint(
            "provider",
            "provider_work_id",
            name="uq_provider_work_records_provider_work_id",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(GUID(), primary_key=True, default=uuid.uuid4)
    canonical_work_id: Mapped[uuid.UUID] = mapped_column(
        GUID(),
        ForeignKey("canonical_works.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    provider: Mapped[str] = mapped_column(String(64), nullable=False)
    provider_work_id: Mapped[str] = mapped_column(String(256), nullable=False)
    raw_metadata: Mapped[dict[str, Any] | None] = mapped_column(JSONType(), nullable=True)
    retrieved_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    canonical_work: Mapped[CanonicalWork] = relationship(back_populates="provider_records")


class SearchSession(Base):
    __tablename__ = "search_sessions"

    id: Mapped[uuid.UUID] = mapped_column(GUID(), primary_key=True, default=uuid.uuid4)
    provider: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    entity: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    query: Mapped[str] = mapped_column(Text, nullable=False)
    normalized_query: Mapped[str] = mapped_column(String(1024), nullable=False, index=True)
    filters: Mapped[dict[str, Any] | None] = mapped_column(JSONType(), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    expires_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, index=True
    )

    results: Mapped[list[SearchSessionResult]] = relationship(
        back_populates="search_session",
        cascade="all, delete-orphan",
    )


class SearchSessionResult(Base):
    __tablename__ = "search_session_results"
    __table_args__ = (
        UniqueConstraint(
            "search_session_id",
            "canonical_entity_type",
            "canonical_entity_id",
            name="uq_search_session_results_entity",
        ),
        Index(
            "ix_search_session_results_session_position",
            "search_session_id",
            "position",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(GUID(), primary_key=True, default=uuid.uuid4)
    search_session_id: Mapped[uuid.UUID] = mapped_column(
        GUID(),
        ForeignKey("search_sessions.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    canonical_entity_type: Mapped[str] = mapped_column(String(64), nullable=False)
    canonical_entity_id: Mapped[uuid.UUID] = mapped_column(GUID(), nullable=False)
    position: Mapped[int] = mapped_column(Integer, nullable=False)
    first_seen_page: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    search_session: Mapped[SearchSession] = relationship(back_populates="results")


class ProviderSearchCache(Base):
    __tablename__ = "provider_search_cache"
    __table_args__ = (
        UniqueConstraint("cache_key", name="uq_provider_search_cache_key"),
        Index(
            "ix_provider_search_cache_lookup",
            "provider",
            "entity",
            "normalized_query",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(GUID(), primary_key=True, default=uuid.uuid4)
    cache_key: Mapped[str] = mapped_column(String(1024), nullable=False)
    provider: Mapped[str] = mapped_column(String(64), nullable=False)
    entity: Mapped[str] = mapped_column(String(64), nullable=False)
    normalized_query: Mapped[str] = mapped_column(String(1024), nullable=False)
    filters: Mapped[dict[str, Any] | None] = mapped_column(JSONType(), nullable=True)
    cursor: Mapped[str | None] = mapped_column(String(512), nullable=True)
    response: Mapped[dict[str, Any]] = mapped_column(JSONType(), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    expires_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, index=True
    )


class WorkGrantMatch(Base):
    __tablename__ = "work_grant_matches"
    __table_args__ = (
        UniqueConstraint(
            "canonical_work_id",
            "provider",
            "normalized_grant_number",
            name="uq_work_grant_matches_work_provider_grant",
        ),
        Index("ix_work_grant_matches_provider", "provider"),
        Index(
            "ix_work_grant_matches_normalized_grant_number",
            "normalized_grant_number",
        ),
        Index(
            "ix_work_grant_matches_provider_normalized_grant_number",
            "provider",
            "normalized_grant_number",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(GUID(), primary_key=True, default=uuid.uuid4)
    canonical_work_id: Mapped[uuid.UUID] = mapped_column(
        GUID(),
        ForeignKey("canonical_works.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    provider: Mapped[str] = mapped_column(String(64), nullable=False)
    grant_number: Mapped[str] = mapped_column(String(256), nullable=False)
    normalized_grant_number: Mapped[str] = mapped_column(String(256), nullable=False)
    verified: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    match_type: Mapped[str] = mapped_column(String(64), nullable=False)
    matched_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    raw_metadata: Mapped[dict[str, Any] | None] = mapped_column(JSONType(), nullable=True)
    retrieved_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    canonical_work: Mapped[CanonicalWork] = relationship(back_populates="grant_matches")


class WorkAuthorship(Base):
    """Authoritative publication-specific authorship identity and affiliations.

    `canonical_author_id` is the source of truth for canonical author-to-work
    membership. `author_works` is retained as a derived provider-work index for
    legacy author identity overlap code.
    """

    __tablename__ = "work_authorships"
    __table_args__ = (
        UniqueConstraint(
            "canonical_work_id",
            "provider",
            "author_position",
            name="uq_work_authorships_work_provider_position",
        ),
        Index("ix_work_authorships_provider_author_id", "provider", "provider_author_id"),
        Index("ix_work_authorships_canonical_author_id", "canonical_author_id"),
        Index("ix_work_authorships_orcid", "orcid"),
    )

    id: Mapped[uuid.UUID] = mapped_column(GUID(), primary_key=True, default=uuid.uuid4)
    canonical_work_id: Mapped[uuid.UUID] = mapped_column(
        GUID(),
        ForeignKey("canonical_works.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    provider: Mapped[str] = mapped_column(String(64), nullable=False)
    provider_author_id: Mapped[str | None] = mapped_column(String(256), nullable=True)
    canonical_author_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID(),
        ForeignKey("canonical_authors.id", ondelete="SET NULL"),
        nullable=True,
    )
    display_name: Mapped[str] = mapped_column(String(512), nullable=False)
    author_position: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    orcid: Mapped[str | None] = mapped_column(String(64), nullable=True)
    institutions: Mapped[list[Any] | None] = mapped_column(JSONType(), nullable=True)
    institution_ids: Mapped[list[Any] | None] = mapped_column(JSONType(), nullable=True)
    countries: Mapped[list[Any] | None] = mapped_column(JSONType(), nullable=True)
    raw_metadata: Mapped[dict[str, Any] | None] = mapped_column(JSONType(), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    canonical_work: Mapped[CanonicalWork] = relationship(back_populates="authorships")


class AuthorWorkSyncState(Base):
    __tablename__ = "author_work_sync_state"
    __table_args__ = (
        UniqueConstraint(
            "canonical_author_id",
            "provider",
            name="uq_author_work_sync_state_author_provider",
        ),
        Index("ix_author_work_sync_state_author", "canonical_author_id"),
        Index("ix_author_work_sync_state_provider_status", "provider", "status"),
    )

    id: Mapped[uuid.UUID] = mapped_column(GUID(), primary_key=True, default=uuid.uuid4)
    canonical_author_id: Mapped[uuid.UUID] = mapped_column(
        GUID(),
        ForeignKey("canonical_authors.id", ondelete="CASCADE"),
        nullable=False,
    )
    provider: Mapped[str] = mapped_column(String(64), nullable=False)
    last_synced_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    stored_work_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    provider_work_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    status: Mapped[str] = mapped_column(String(64), nullable=False, default="never")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )
