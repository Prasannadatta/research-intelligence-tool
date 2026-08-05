"""Author identity resolution ORM models."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import (
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.types import JSON, TypeDecorator, Uuid

from app.db.base import Base


class JSONType(TypeDecorator):
    """Portable JSON/JSONB column."""

    impl = JSON
    cache_ok = True

    def load_dialect_impl(self, dialect):
        if dialect.name == "postgresql":
            return dialect.type_descriptor(JSONB())
        return dialect.type_descriptor(JSON())


class GUID(TypeDecorator):
    """Portable UUID type."""

    impl = Uuid
    cache_ok = True

    def load_dialect_impl(self, dialect):
        if dialect.name == "postgresql":
            return dialect.type_descriptor(UUID(as_uuid=True))
        return dialect.type_descriptor(String(36))

    def process_bind_param(self, value, dialect):
        if value is None:
            return value
        if dialect.name == "postgresql":
            return value if isinstance(value, uuid.UUID) else uuid.UUID(str(value))
        return str(value)

    def process_result_value(self, value, dialect):
        if value is None:
            return value
        return value if isinstance(value, uuid.UUID) else uuid.UUID(str(value))


class CanonicalAuthor(Base):
    __tablename__ = "canonical_authors"

    id: Mapped[uuid.UUID] = mapped_column(GUID(), primary_key=True, default=uuid.uuid4)
    preferred_name: Mapped[str] = mapped_column(String(512), nullable=False)
    normalized_name: Mapped[str] = mapped_column(String(512), nullable=False, index=True)
    surname: Mapped[str | None] = mapped_column(String(256), nullable=True, index=True)
    first_initial: Mapped[str | None] = mapped_column(String(8), nullable=True, index=True)
    resolution_status: Mapped[str] = mapped_column(
        String(64), nullable=False, default="unresolved"
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

    provider_records: Mapped[list["ProviderAuthorRecord"]] = relationship(
        back_populates="canonical_author",
        cascade="all, delete-orphan",
    )
    aliases: Mapped[list["AuthorAlias"]] = relationship(
        back_populates="canonical_author",
        cascade="all, delete-orphan",
    )


class ProviderAuthorRecord(Base):
    __tablename__ = "provider_author_records"
    __table_args__ = (
        UniqueConstraint("provider", "provider_author_id", name="uq_provider_author"),
        Index("ix_provider_author_normalized_name", "normalized_name"),
        Index("ix_provider_author_surname_initial", "surname", "first_initial"),
        Index("ix_provider_author_orcid", "orcid"),
    )

    id: Mapped[uuid.UUID] = mapped_column(GUID(), primary_key=True, default=uuid.uuid4)
    canonical_author_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID(),
        ForeignKey("canonical_authors.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    provider: Mapped[str] = mapped_column(String(64), nullable=False)
    provider_author_id: Mapped[str] = mapped_column(String(256), nullable=False)
    display_name: Mapped[str] = mapped_column(String(512), nullable=False)
    normalized_name: Mapped[str] = mapped_column(String(512), nullable=False)
    surname: Mapped[str | None] = mapped_column(String(256), nullable=True)
    first_initial: Mapped[str | None] = mapped_column(String(8), nullable=True)
    orcid: Mapped[str | None] = mapped_column(String(64), nullable=True)
    works_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    raw_metadata: Mapped[dict[str, Any] | None] = mapped_column(JSONType, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    canonical_author: Mapped[CanonicalAuthor | None] = relationship(
        back_populates="provider_records"
    )
    institutions: Mapped[list[AuthorInstitution]] = relationship(
        back_populates="provider_record",
        cascade="all, delete-orphan",
    )
    works: Mapped[list[AuthorWork]] = relationship(
        back_populates="provider_record",
        cascade="all, delete-orphan",
    )


class AuthorAlias(Base):
    __tablename__ = "author_aliases"
    __table_args__ = (
        UniqueConstraint(
            "canonical_author_id",
            "normalized_alias",
            name="uq_canonical_alias",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(GUID(), primary_key=True, default=uuid.uuid4)
    canonical_author_id: Mapped[uuid.UUID] = mapped_column(
        GUID(),
        ForeignKey("canonical_authors.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    alias: Mapped[str] = mapped_column(String(512), nullable=False)
    normalized_alias: Mapped[str] = mapped_column(String(512), nullable=False, index=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    canonical_author: Mapped[CanonicalAuthor] = relationship(back_populates="aliases")


class AuthorInstitution(Base):
    __tablename__ = "author_institutions"
    __table_args__ = (
        Index("ix_author_institution_provider_id", "institution_id"),
        Index("ix_author_institution_normalized_name", "normalized_name"),
    )

    id: Mapped[uuid.UUID] = mapped_column(GUID(), primary_key=True, default=uuid.uuid4)
    provider_author_record_id: Mapped[uuid.UUID] = mapped_column(
        GUID(),
        ForeignKey("provider_author_records.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    institution_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    display_name: Mapped[str | None] = mapped_column(String(512), nullable=True)
    normalized_name: Mapped[str | None] = mapped_column(String(512), nullable=True)
    country_code: Mapped[str | None] = mapped_column(String(8), nullable=True)

    provider_record: Mapped[ProviderAuthorRecord] = relationship(
        back_populates="institutions"
    )


class AuthorWork(Base):
    __tablename__ = "author_works"
    __table_args__ = (
        UniqueConstraint(
            "provider_author_record_id",
            "work_id",
            name="uq_provider_record_work",
        ),
        Index("ix_author_work_work_id", "work_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(GUID(), primary_key=True, default=uuid.uuid4)
    provider_author_record_id: Mapped[uuid.UUID] = mapped_column(
        GUID(),
        ForeignKey("provider_author_records.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    work_id: Mapped[str] = mapped_column(String(256), nullable=False)
    work_id_type: Mapped[str | None] = mapped_column(String(64), nullable=True)
    title: Mapped[str | None] = mapped_column(Text, nullable=True)
    publication_year: Mapped[int | None] = mapped_column(Integer, nullable=True)

    provider_record: Mapped[ProviderAuthorRecord] = relationship(back_populates="works")


class AuthorMatchEvidence(Base):
    __tablename__ = "author_match_evidence"
    __table_args__ = (
        Index("ix_match_evidence_pair", "record_a_id", "record_b_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(GUID(), primary_key=True, default=uuid.uuid4)
    record_a_id: Mapped[uuid.UUID] = mapped_column(
        GUID(),
        ForeignKey("provider_author_records.id", ondelete="CASCADE"),
        nullable=False,
    )
    record_b_id: Mapped[uuid.UUID] = mapped_column(
        GUID(),
        ForeignKey("provider_author_records.id", ondelete="CASCADE"),
        nullable=False,
    )
    total_score: Mapped[float] = mapped_column(Float, nullable=False)
    name_score: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    institution_score: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    work_overlap_score: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    coauthor_score: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    decision: Mapped[str] = mapped_column(String(64), nullable=False)
    reasoning: Mapped[dict[str, Any] | None] = mapped_column(JSONType, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
