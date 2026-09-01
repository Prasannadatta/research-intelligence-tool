"""Add author work sync state."""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy import inspect

revision = "007_author_work_sync_state"
down_revision = "006_work_authorships"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)
    table_names = set(inspector.get_table_names())
    if "author_work_sync_state" not in table_names:
        op.create_table(
            "author_work_sync_state",
            sa.Column("id", sa.String(36), primary_key=True),
            sa.Column(
                "canonical_author_id",
                sa.String(36),
                sa.ForeignKey("canonical_authors.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column("provider", sa.String(64), nullable=False),
            sa.Column("last_synced_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("stored_work_count", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("provider_work_count", sa.Integer(), nullable=True),
            sa.Column("status", sa.String(64), nullable=False, server_default="never"),
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
            sa.UniqueConstraint(
                "canonical_author_id",
                "provider",
                name="uq_author_work_sync_state_author_provider",
            ),
        )
    index_names = {
        row["name"] for row in inspector.get_indexes("author_work_sync_state")
    }
    if "ix_author_work_sync_state_author" not in index_names:
        op.create_index(
            "ix_author_work_sync_state_author",
            "author_work_sync_state",
            ["canonical_author_id"],
        )
    if "ix_author_work_sync_state_provider_status" not in index_names:
        op.create_index(
            "ix_author_work_sync_state_provider_status",
            "author_work_sync_state",
            ["provider", "status"],
        )


def downgrade() -> None:
    op.drop_index(
        "ix_author_work_sync_state_provider_status",
        table_name="author_work_sync_state",
    )
    op.drop_index("ix_author_work_sync_state_author", table_name="author_work_sync_state")
    op.drop_table("author_work_sync_state")
