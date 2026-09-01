"""Cached Scopus cited-by identifiers, citing works, and citation links."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import (
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


class ScopusCitedBySync(Base):
    """Per-canonical-work cache/sync state for Scopus cited-by retrieval."""

    __tablename__ = "scopus_cited_by_sync"
    __table_args__ = (
        UniqueConstraint("canonical_work_id", name="uq_scopus_cited_by_sync_canonical_work"),
        Index("ix_scopus_cited_by_sync_status_expires", "status", "expires_at"),
        Index("ix_scopus_cited_by_sync_scopus_id", "scopus_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(GUID(), primary_key=True, default=uuid.uuid4)
    canonical_work_id: Mapped[uuid.UUID] = mapped_column(
        GUID(),
        ForeignKey("canonical_works.id", ondelete="CASCADE"),
        nullable=False,
    )
    scopus_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    eid: Mapped[str | None] = mapped_column(String(128), nullable=True)
    citedby_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="never")
    last_synced_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    fetched_result_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )


class ScopusCitingWork(Base):
    """A unique citing document retrieved from Scopus Search REF()."""

    __tablename__ = "scopus_citing_works"
    __table_args__ = (
        UniqueConstraint("scopus_id", name="uq_scopus_citing_works_scopus_id"),
        UniqueConstraint("eid", name="uq_scopus_citing_works_eid"),
        Index("ix_scopus_citing_works_normalized_doi", "normalized_doi"),
        Index("ix_scopus_citing_works_publication_year", "publication_year"),
    )

    id: Mapped[uuid.UUID] = mapped_column(GUID(), primary_key=True, default=uuid.uuid4)
    scopus_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    eid: Mapped[str | None] = mapped_column(String(128), nullable=True)
    doi: Mapped[str | None] = mapped_column(String(512), nullable=True)
    normalized_doi: Mapped[str | None] = mapped_column(String(512), nullable=True)
    title: Mapped[str | None] = mapped_column(String(2048), nullable=True)
    cover_date: Mapped[str | None] = mapped_column(String(32), nullable=True)
    publication_year: Mapped[int | None] = mapped_column(Integer, nullable=True)
    source_title: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    affiliations: Mapped[list[dict[str, Any]] | None] = mapped_column(JSONType(), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    citation_links: Mapped[list["ScopusCitationLink"]] = relationship(
        back_populates="citing_work",
        cascade="all, delete-orphan",
    )


class ScopusCitationLink(Base):
    """Citing work → cited canonical work (and source Scopus ID)."""

    __tablename__ = "scopus_citation_links"
    __table_args__ = (
        UniqueConstraint(
            "citing_work_id",
            "cited_canonical_work_id",
            name="uq_scopus_citation_links_citing_cited",
        ),
        Index("ix_scopus_citation_links_cited_canonical", "cited_canonical_work_id"),
        Index("ix_scopus_citation_links_cited_scopus_id", "cited_scopus_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(GUID(), primary_key=True, default=uuid.uuid4)
    citing_work_id: Mapped[uuid.UUID] = mapped_column(
        GUID(),
        ForeignKey("scopus_citing_works.id", ondelete="CASCADE"),
        nullable=False,
    )
    cited_canonical_work_id: Mapped[uuid.UUID] = mapped_column(
        GUID(),
        ForeignKey("canonical_works.id", ondelete="CASCADE"),
        nullable=False,
    )
    cited_scopus_id: Mapped[str | None] = mapped_column(String(64), nullable=True)

    citing_work: Mapped[ScopusCitingWork] = relationship(back_populates="citation_links")
