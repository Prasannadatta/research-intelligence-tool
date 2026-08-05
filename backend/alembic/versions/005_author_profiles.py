"""Add author_profiles and canonical_author_institutions tables."""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "005_author_profiles"
down_revision = "004_author_analysis_searches"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "author_profiles",
        sa.Column("canonical_author_id", sa.String(36), sa.ForeignKey("canonical_authors.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("orcid", sa.String(64), nullable=True),
        sa.Column("works_count", sa.Integer(), nullable=True),
        sa.Column("citation_count", sa.Integer(), nullable=True),
        sa.Column("h_index", sa.Integer(), nullable=True),
        sa.Column("topics", sa.JSON(), nullable=True),
        sa.Column("providers", sa.JSON(), nullable=True),
        sa.Column("enriched_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
    )
    op.create_index("ix_author_profiles_orcid", "author_profiles", ["orcid"])

    op.create_table(
        "canonical_author_institutions",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("canonical_author_id", sa.String(36), sa.ForeignKey("canonical_authors.id", ondelete="CASCADE"), nullable=False),
        sa.Column("institution_id", sa.String(128), nullable=True),
        sa.Column("institution_key", sa.String(512), nullable=False),
        sa.Column("institution_name", sa.String(512), nullable=True),
        sa.Column("department", sa.String(512), nullable=True),
        sa.Column("country_code", sa.String(8), nullable=True),
        sa.Column("valid_from_year", sa.Integer(), nullable=True),
        sa.Column("valid_to_year", sa.Integer(), nullable=True),
        sa.Column("is_current", sa.Boolean(), nullable=False, server_default=sa.text("0")),
        sa.Column("provider", sa.String(64), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.UniqueConstraint("canonical_author_id", "institution_key", name="uq_canonical_author_institution"),
    )
    op.create_index(
        "ix_canonical_author_institution_canonical",
        "canonical_author_institutions",
        ["canonical_author_id"],
    )
    op.create_index(
        "ix_canonical_author_institution_current",
        "canonical_author_institutions",
        ["canonical_author_id", "is_current"],
    )


def downgrade() -> None:
    op.drop_table("canonical_author_institutions")
    op.drop_table("author_profiles")
