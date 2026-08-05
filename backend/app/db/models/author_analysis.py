"""Persisted author publication analysis combinations."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, Index, Integer, String, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.db.models.author_identity import GUID, JSONType


class AuthorAnalysisSearch(Base):
    __tablename__ = "author_analysis_searches"
    __table_args__ = (
        UniqueConstraint("combination_key", name="uq_author_analysis_combination_key"),
        Index("ix_author_analysis_searches_mode", "mode"),
    )

    id: Mapped[uuid.UUID] = mapped_column(GUID(), primary_key=True, default=uuid.uuid4)
    combination_key: Mapped[str] = mapped_column(String(512), nullable=False)
    original_author_ids: Mapped[list[Any]] = mapped_column(JSONType, nullable=False)
    active_author_ids: Mapped[list[Any]] = mapped_column(JSONType, nullable=False)
    active_author_names: Mapped[list[Any]] = mapped_column(JSONType, nullable=False)
    mode: Mapped[str] = mapped_column(String(64), nullable=False)
    provider_records: Mapped[list[Any]] = mapped_column(JSONType, nullable=False, default=list)
    result_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )
