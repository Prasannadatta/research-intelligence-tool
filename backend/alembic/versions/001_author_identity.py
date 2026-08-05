"""Initial author identity resolution tables.

Revision ID: 001_author_identity
Revises:
Create Date: 2026-07-22
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "001_author_identity"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "canonical_authors",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("preferred_name", sa.String(length=512), nullable=False),
        sa.Column("normalized_name", sa.String(length=512), nullable=False),
        sa.Column("surname", sa.String(length=256), nullable=True),
        sa.Column("first_initial", sa.String(length=8), nullable=True),
        sa.Column("resolution_status", sa.String(length=64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_canonical_authors_normalized_name", "canonical_authors", ["normalized_name"])
    op.create_index("ix_canonical_authors_surname", "canonical_authors", ["surname"])
    op.create_index("ix_canonical_authors_first_initial", "canonical_authors", ["first_initial"])

    op.create_table(
        "provider_author_records",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("canonical_author_id", sa.String(length=36), sa.ForeignKey("canonical_authors.id", ondelete="SET NULL"), nullable=True),
        sa.Column("provider", sa.String(length=64), nullable=False),
        sa.Column("provider_author_id", sa.String(length=256), nullable=False),
        sa.Column("display_name", sa.String(length=512), nullable=False),
        sa.Column("normalized_name", sa.String(length=512), nullable=False),
        sa.Column("surname", sa.String(length=256), nullable=True),
        sa.Column("first_initial", sa.String(length=8), nullable=True),
        sa.Column("orcid", sa.String(length=64), nullable=True),
        sa.Column("works_count", sa.Integer(), nullable=True),
        sa.Column("raw_metadata", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("provider", "provider_author_id", name="uq_provider_author"),
    )
    op.create_index("ix_provider_author_records_canonical_author_id", "provider_author_records", ["canonical_author_id"])
    op.create_index("ix_provider_author_normalized_name", "provider_author_records", ["normalized_name"])
    op.create_index("ix_provider_author_surname_initial", "provider_author_records", ["surname", "first_initial"])
    op.create_index("ix_provider_author_orcid", "provider_author_records", ["orcid"])

    op.create_table(
        "author_aliases",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("canonical_author_id", sa.String(length=36), sa.ForeignKey("canonical_authors.id", ondelete="CASCADE"), nullable=False),
        sa.Column("alias", sa.String(length=512), nullable=False),
        sa.Column("normalized_alias", sa.String(length=512), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("canonical_author_id", "normalized_alias", name="uq_canonical_alias"),
    )
    op.create_index("ix_author_aliases_canonical_author_id", "author_aliases", ["canonical_author_id"])
    op.create_index("ix_author_aliases_normalized_alias", "author_aliases", ["normalized_alias"])

    op.create_table(
        "author_institutions",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("provider_author_record_id", sa.String(length=36), sa.ForeignKey("provider_author_records.id", ondelete="CASCADE"), nullable=False),
        sa.Column("institution_id", sa.String(length=128), nullable=True),
        sa.Column("display_name", sa.String(length=512), nullable=True),
        sa.Column("normalized_name", sa.String(length=512), nullable=True),
        sa.Column("country_code", sa.String(length=8), nullable=True),
    )
    op.create_index("ix_author_institutions_provider_author_record_id", "author_institutions", ["provider_author_record_id"])
    op.create_index("ix_author_institution_provider_id", "author_institutions", ["institution_id"])
    op.create_index("ix_author_institution_normalized_name", "author_institutions", ["normalized_name"])

    op.create_table(
        "author_works",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("provider_author_record_id", sa.String(length=36), sa.ForeignKey("provider_author_records.id", ondelete="CASCADE"), nullable=False),
        sa.Column("work_id", sa.String(length=256), nullable=False),
        sa.Column("work_id_type", sa.String(length=64), nullable=True),
        sa.Column("title", sa.Text(), nullable=True),
        sa.Column("publication_year", sa.Integer(), nullable=True),
        sa.UniqueConstraint("provider_author_record_id", "work_id", name="uq_provider_record_work"),
    )
    op.create_index("ix_author_works_provider_author_record_id", "author_works", ["provider_author_record_id"])
    op.create_index("ix_author_work_work_id", "author_works", ["work_id"])

    op.create_table(
        "author_match_evidence",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("record_a_id", sa.String(length=36), sa.ForeignKey("provider_author_records.id", ondelete="CASCADE"), nullable=False),
        sa.Column("record_b_id", sa.String(length=36), sa.ForeignKey("provider_author_records.id", ondelete="CASCADE"), nullable=False),
        sa.Column("total_score", sa.Float(), nullable=False),
        sa.Column("name_score", sa.Float(), nullable=False),
        sa.Column("institution_score", sa.Float(), nullable=False),
        sa.Column("work_overlap_score", sa.Float(), nullable=False),
        sa.Column("coauthor_score", sa.Float(), nullable=False),
        sa.Column("decision", sa.String(length=64), nullable=False),
        sa.Column("reasoning", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_match_evidence_pair", "author_match_evidence", ["record_a_id", "record_b_id"])


def downgrade() -> None:
    op.drop_table("author_match_evidence")
    op.drop_table("author_works")
    op.drop_table("author_institutions")
    op.drop_table("author_aliases")
    op.drop_table("provider_author_records")
    op.drop_table("canonical_authors")
