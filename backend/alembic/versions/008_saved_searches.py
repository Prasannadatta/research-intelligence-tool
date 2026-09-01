"""Add saved searches."""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy import inspect

revision = "008_saved_searches"
down_revision = "007_author_work_sync_state"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)
    table_names = set(inspector.get_table_names())
    if "saved_searches" not in table_names:
        op.create_table(
            "saved_searches",
            sa.Column("id", sa.String(36), primary_key=True),
            sa.Column("search_type", sa.String(32), nullable=False),
            sa.Column("display_name", sa.String(512), nullable=False),
            sa.Column("canonical_key", sa.String(128), nullable=False),
            sa.Column("payload", sa.JSON(), nullable=False),
            sa.Column("applied_filters", sa.JSON(), nullable=False),
            sa.Column("provider_context", sa.JSON(), nullable=False),
            sa.Column("excluded_work_ids", sa.JSON(), nullable=True),
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
            sa.Column("last_viewed_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("view_count", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("is_pinned", sa.Boolean(), nullable=False, server_default=sa.false()),
            sa.Column("notes", sa.Text(), nullable=True),
            sa.Column("metadata", sa.JSON(), nullable=True),
            sa.UniqueConstraint("canonical_key", name="uq_saved_searches_canonical_key"),
        )

    index_names = {row["name"] for row in inspector.get_indexes("saved_searches")}
    if "ix_saved_searches_search_type" not in index_names:
        op.create_index("ix_saved_searches_search_type", "saved_searches", ["search_type"])
    if "ix_saved_searches_last_viewed_at" not in index_names:
        op.create_index(
            "ix_saved_searches_last_viewed_at",
            "saved_searches",
            ["last_viewed_at"],
        )
    if "ix_saved_searches_updated_at" not in index_names:
        op.create_index("ix_saved_searches_updated_at", "saved_searches", ["updated_at"])


def downgrade() -> None:
    op.drop_index("ix_saved_searches_updated_at", table_name="saved_searches")
    op.drop_index("ix_saved_searches_last_viewed_at", table_name="saved_searches")
    op.drop_index("ix_saved_searches_search_type", table_name="saved_searches")
    op.drop_table("saved_searches")
