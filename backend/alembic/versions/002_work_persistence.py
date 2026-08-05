"""Canonical works, search sessions, provider cache, grant provenance.

Revision ID: 002_work_persistence
Revises: 001_author_identity
Create Date: 2026-07-22
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "002_work_persistence"
down_revision: Union[str, None] = "001_author_identity"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "canonical_works",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("title", sa.String(length=1024), nullable=False),
        sa.Column("normalized_title", sa.String(length=1024), nullable=False),
        sa.Column("publication_year", sa.Integer(), nullable=True),
        sa.Column("normalized_first_author", sa.String(length=512), nullable=True),
        sa.Column("doi", sa.String(length=512), nullable=True),
        sa.Column("arxiv_id", sa.String(length=128), nullable=True),
        sa.Column("pmid", sa.String(length=64), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )
    op.create_index("ix_canonical_works_normalized_title", "canonical_works", ["normalized_title"])
    op.create_index("ix_canonical_works_doi", "canonical_works", ["doi"])
    op.create_index("ix_canonical_works_arxiv_id", "canonical_works", ["arxiv_id"])
    op.create_index("ix_canonical_works_pmid", "canonical_works", ["pmid"])
    op.create_index(
        "ix_canonical_works_title_year_author",
        "canonical_works",
        ["normalized_title", "publication_year", "normalized_first_author"],
    )

    op.create_table(
        "provider_work_records",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column(
            "canonical_work_id",
            sa.String(length=36),
            sa.ForeignKey("canonical_works.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("provider", sa.String(length=64), nullable=False),
        sa.Column("provider_work_id", sa.String(length=256), nullable=False),
        sa.Column("raw_metadata", sa.JSON(), nullable=True),
        sa.Column(
            "retrieved_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.UniqueConstraint(
            "provider",
            "provider_work_id",
            name="uq_provider_work_records_provider_work_id",
        ),
    )
    op.create_index(
        "ix_provider_work_records_canonical_work_id",
        "provider_work_records",
        ["canonical_work_id"],
    )

    op.create_table(
        "search_sessions",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("provider", sa.String(length=64), nullable=False),
        sa.Column("entity", sa.String(length=64), nullable=False),
        sa.Column("query", sa.Text(), nullable=False),
        sa.Column("normalized_query", sa.String(length=1024), nullable=False),
        sa.Column("filters", sa.JSON(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_search_sessions_provider", "search_sessions", ["provider"])
    op.create_index("ix_search_sessions_entity", "search_sessions", ["entity"])
    op.create_index(
        "ix_search_sessions_normalized_query",
        "search_sessions",
        ["normalized_query"],
    )
    op.create_index("ix_search_sessions_expires_at", "search_sessions", ["expires_at"])

    op.create_table(
        "search_session_results",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column(
            "search_session_id",
            sa.String(length=36),
            sa.ForeignKey("search_sessions.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("canonical_entity_type", sa.String(length=64), nullable=False),
        sa.Column("canonical_entity_id", sa.String(length=36), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("first_seen_page", sa.Integer(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.UniqueConstraint(
            "search_session_id",
            "canonical_entity_type",
            "canonical_entity_id",
            name="uq_search_session_results_entity",
        ),
    )
    op.create_index(
        "ix_search_session_results_search_session_id",
        "search_session_results",
        ["search_session_id"],
    )
    op.create_index(
        "ix_search_session_results_session_position",
        "search_session_results",
        ["search_session_id", "position"],
    )

    op.create_table(
        "provider_search_cache",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("cache_key", sa.String(length=1024), nullable=False),
        sa.Column("provider", sa.String(length=64), nullable=False),
        sa.Column("entity", sa.String(length=64), nullable=False),
        sa.Column("normalized_query", sa.String(length=1024), nullable=False),
        sa.Column("filters", sa.JSON(), nullable=True),
        sa.Column("cursor", sa.String(length=512), nullable=True),
        sa.Column("response", sa.JSON(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("cache_key", name="uq_provider_search_cache_key"),
    )
    op.create_index(
        "ix_provider_search_cache_lookup",
        "provider_search_cache",
        ["provider", "entity", "normalized_query"],
    )
    op.create_index(
        "ix_provider_search_cache_expires_at",
        "provider_search_cache",
        ["expires_at"],
    )

    op.create_table(
        "work_grant_matches",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column(
            "canonical_work_id",
            sa.String(length=36),
            sa.ForeignKey("canonical_works.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("provider", sa.String(length=64), nullable=False),
        sa.Column("grant_number", sa.String(length=256), nullable=False),
        sa.Column("normalized_grant_number", sa.String(length=256), nullable=False),
        sa.Column("verified", sa.Boolean(), nullable=False),
        sa.Column("match_type", sa.String(length=64), nullable=False),
        sa.Column("matched_text", sa.Text(), nullable=True),
        sa.Column("raw_metadata", sa.JSON(), nullable=True),
        sa.Column(
            "retrieved_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.UniqueConstraint(
            "canonical_work_id",
            "provider",
            "normalized_grant_number",
            name="uq_work_grant_matches_work_provider_grant",
        ),
    )
    op.create_index(
        "ix_work_grant_matches_canonical_work_id",
        "work_grant_matches",
        ["canonical_work_id"],
    )


def downgrade() -> None:
    op.drop_table("work_grant_matches")
    op.drop_table("provider_search_cache")
    op.drop_table("search_session_results")
    op.drop_table("search_sessions")
    op.drop_table("provider_work_records")
    op.drop_table("canonical_works")
