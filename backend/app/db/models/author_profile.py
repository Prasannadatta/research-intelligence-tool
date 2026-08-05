"""Enriched canonical author profile storage."""

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
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.models.author_identity import GUID, JSONType
from app.db.base import Base


class AuthorProfile(Base):
    __tablename__ = "author_profiles"

    canonical_author_id: Mapped[uuid.UUID] = mapped_column(
        GUID(),
        ForeignKey("canonical_authors.id", ondelete="CASCADE"),
        primary_key=True,
    )
    orcid: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    works_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    citation_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    h_index: Mapped[int | None] = mapped_column(Integer, nullable=True)
    topics: Mapped[list[Any] | None] = mapped_column(JSONType, nullable=True)
    providers: Mapped[list[Any] | None] = mapped_column(JSONType, nullable=True)
    enriched_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
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


class CanonicalAuthorInstitution(Base):
    __tablename__ = "canonical_author_institutions"
    __table_args__ = (
        UniqueConstraint(
            "canonical_author_id",
            "institution_key",
            name="uq_canonical_author_institution",
        ),
        Index("ix_canonical_author_institution_current", "canonical_author_id", "is_current"),
    )

    id: Mapped[uuid.UUID] = mapped_column(GUID(), primary_key=True, default=uuid.uuid4)
    canonical_author_id: Mapped[uuid.UUID] = mapped_column(
        GUID(),
        ForeignKey("canonical_authors.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    institution_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    institution_key: Mapped[str] = mapped_column(String(512), nullable=False)
    institution_name: Mapped[str | None] = mapped_column(String(512), nullable=True)
    department: Mapped[str | None] = mapped_column(String(512), nullable=True)
    country_code: Mapped[str | None] = mapped_column(String(8), nullable=True)
    valid_from_year: Mapped[int | None] = mapped_column(Integer, nullable=True)
    valid_to_year: Mapped[int | None] = mapped_column(Integer, nullable=True)
    is_current: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    provider: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )
