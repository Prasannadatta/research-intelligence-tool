"""Cached Scopus journal metrics keyed by ISSN."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, Float, ForeignKey, Index, Integer, String, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.db.models.author_identity import GUID, JSONType


class JournalMetrics(Base):
    __tablename__ = "journal_metrics"
    __table_args__ = (
        UniqueConstraint("normalized_issn", name="uq_journal_metrics_normalized_issn"),
        Index("ix_journal_metrics_scopus_source_id", "scopus_source_id"),
        Index("ix_journal_metrics_status_expires", "status", "expires_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(GUID(), primary_key=True, default=uuid.uuid4)
    normalized_issn: Mapped[str] = mapped_column(String(16), nullable=False)
    print_issn: Mapped[str | None] = mapped_column(String(16), nullable=True)
    electronic_issn: Mapped[str | None] = mapped_column(String(16), nullable=True)
    journal_name: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    scopus_source_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    scopus_url: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    citescore: Mapped[float | None] = mapped_column(Float, nullable=True)
    citescore_year: Mapped[int | None] = mapped_column(Integer, nullable=True)
    sjr: Mapped[float | None] = mapped_column(Float, nullable=True)
    sjr_year: Mapped[int | None] = mapped_column(Integer, nullable=True)
    snip: Mapped[float | None] = mapped_column(Float, nullable=True)
    snip_year: Mapped[int | None] = mapped_column(Integer, nullable=True)
    source: Mapped[str] = mapped_column(String(32), nullable=False, default="scopus")
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="success")
    retrieved_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    raw_metadata: Mapped[dict[str, Any] | None] = mapped_column(JSONType(), nullable=True)

    issn_aliases: Mapped[list["JournalIssnAlias"]] = relationship(
        back_populates="journal_metrics",
        cascade="all, delete-orphan",
    )


class JournalIssnAlias(Base):
    """Maps print/eISSN compact forms onto a single journal_metrics row."""

    __tablename__ = "journal_issn_aliases"
    __table_args__ = (
        UniqueConstraint("normalized_issn", name="uq_journal_issn_aliases_normalized_issn"),
    )

    id: Mapped[uuid.UUID] = mapped_column(GUID(), primary_key=True, default=uuid.uuid4)
    normalized_issn: Mapped[str] = mapped_column(String(16), nullable=False)
    journal_metrics_id: Mapped[uuid.UUID] = mapped_column(
        GUID(),
        ForeignKey("journal_metrics.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    journal_metrics: Mapped[JournalMetrics] = relationship(back_populates="issn_aliases")
