"""Add analysis_jobs for background Collaboration Insights."""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy import inspect

revision = "013_analysis_jobs"
down_revision = "012_remove_auth_users"
branch_labels = None
depends_on = None


def _index_names(inspector, table_name: str) -> set[str]:
    return {row["name"] for row in inspector.get_indexes(table_name)}


def upgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)
    table_names = set(inspector.get_table_names())

    if "analysis_jobs" not in table_names:
        op.create_table(
            "analysis_jobs",
            sa.Column("id", sa.String(36), primary_key=True),
            sa.Column("status", sa.String(32), nullable=False, server_default="queued"),
            sa.Column("request_payload", sa.JSON(), nullable=False),
            sa.Column("result", sa.JSON(), nullable=True),
            sa.Column("progress_percent", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("progress_stage", sa.String(128), nullable=True),
            sa.Column("error_message", sa.Text(), nullable=True),
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
            sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        )
    indexes = _index_names(inspector, "analysis_jobs")
    if "ix_analysis_jobs_status" not in indexes:
        op.create_index("ix_analysis_jobs_status", "analysis_jobs", ["status"])
    if "ix_analysis_jobs_created_at" not in indexes:
        op.create_index("ix_analysis_jobs_created_at", "analysis_jobs", ["created_at"])


def downgrade() -> None:
    op.drop_index("ix_analysis_jobs_created_at", table_name="analysis_jobs")
    op.drop_index("ix_analysis_jobs_status", table_name="analysis_jobs")
    op.drop_table("analysis_jobs")
