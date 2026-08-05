"""Add author_analysis_searches table."""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "004_author_analysis_searches"
down_revision = "003_work_grant_match_indexes"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "author_analysis_searches",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("combination_key", sa.String(512), nullable=False),
        sa.Column("original_author_ids", sa.JSON(), nullable=False),
        sa.Column("active_author_ids", sa.JSON(), nullable=False),
        sa.Column("active_author_names", sa.JSON(), nullable=False),
        sa.Column("mode", sa.String(64), nullable=False),
        sa.Column("provider_records", sa.JSON(), nullable=False),
        sa.Column("result_count", sa.Integer(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.UniqueConstraint("combination_key", name="uq_author_analysis_combination_key"),
    )
    op.create_index(
        "ix_author_analysis_searches_mode",
        "author_analysis_searches",
        ["mode"],
    )


def downgrade() -> None:
    op.drop_index("ix_author_analysis_searches_mode", table_name="author_analysis_searches")
    op.drop_table("author_analysis_searches")
