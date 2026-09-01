"""Add data updater jobs and refresh metadata."""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy import inspect

revision = "009_data_update_jobs"
down_revision = "008_saved_searches"
branch_labels = None
depends_on = None


def _index_names(inspector, table_name: str) -> set[str]:
    return {row["name"] for row in inspector.get_indexes(table_name)}


def upgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)
    table_names = set(inspector.get_table_names())

    if "data_update_jobs" not in table_names:
        op.create_table(
            "data_update_jobs",
            sa.Column("id", sa.String(36), primary_key=True),
            sa.Column("mode", sa.String(64), nullable=False),
            sa.Column("dataset", sa.String(128), nullable=True),
            sa.Column("status", sa.String(64), nullable=False, server_default="queued"),
            sa.Column("current_dataset", sa.String(128), nullable=True),
            sa.Column("total_records", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("processed_records", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("updated_count", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("unchanged_count", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("retrying_count", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("failed_count", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("requested_record_ids", sa.JSON(), nullable=True),
            sa.Column("metadata", sa.JSON(), nullable=True),
            sa.Column("error", sa.Text(), nullable=True),
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
    indexes = _index_names(inspector, "data_update_jobs")
    if "ix_data_update_jobs_status" not in indexes:
        op.create_index("ix_data_update_jobs_status", "data_update_jobs", ["status"])
    if "ix_data_update_jobs_created_at" not in indexes:
        op.create_index("ix_data_update_jobs_created_at", "data_update_jobs", ["created_at"])

    if "data_update_job_records" not in table_names:
        op.create_table(
            "data_update_job_records",
            sa.Column("id", sa.String(36), primary_key=True),
            sa.Column("job_id", sa.String(36), nullable=False),
            sa.Column("dataset", sa.String(128), nullable=False),
            sa.Column("record_id", sa.String(256), nullable=False),
            sa.Column("source", sa.String(64), nullable=True),
            sa.Column("status", sa.String(64), nullable=False),
            sa.Column("message", sa.Text(), nullable=True),
            sa.Column("retry_count", sa.Integer(), nullable=False, server_default="0"),
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
        )
    indexes = _index_names(inspector, "data_update_job_records")
    if "ix_data_update_job_records_job" not in indexes:
        op.create_index("ix_data_update_job_records_job", "data_update_job_records", ["job_id"])
    if "ix_data_update_job_records_dataset_status" not in indexes:
        op.create_index(
            "ix_data_update_job_records_dataset_status",
            "data_update_job_records",
            ["dataset", "status"],
        )

    if "refresh_subject_states" not in table_names:
        op.create_table(
            "refresh_subject_states",
            sa.Column("id", sa.String(36), primary_key=True),
            sa.Column("dataset", sa.String(128), nullable=False),
            sa.Column("record_id", sa.String(256), nullable=False),
            sa.Column("source", sa.String(64), nullable=True),
            sa.Column("last_updated", sa.DateTime(timezone=True), nullable=True),
            sa.Column("last_successful_refresh", sa.DateTime(timezone=True), nullable=True),
            sa.Column("refresh_status", sa.String(64), nullable=False, server_default="never"),
            sa.Column("last_error", sa.Text(), nullable=True),
            sa.Column("retry_count", sa.Integer(), nullable=False, server_default="0"),
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
            sa.UniqueConstraint("dataset", "record_id", name="uq_refresh_subject_dataset_record"),
        )
    indexes = _index_names(inspector, "refresh_subject_states")
    if "ix_refresh_subject_dataset_status" not in indexes:
        op.create_index(
            "ix_refresh_subject_dataset_status",
            "refresh_subject_states",
            ["dataset", "refresh_status"],
        )
    if "ix_refresh_subject_success" not in indexes:
        op.create_index(
            "ix_refresh_subject_success",
            "refresh_subject_states",
            ["dataset", "last_successful_refresh"],
        )


def downgrade() -> None:
    op.drop_index("ix_refresh_subject_success", table_name="refresh_subject_states")
    op.drop_index("ix_refresh_subject_dataset_status", table_name="refresh_subject_states")
    op.drop_table("refresh_subject_states")
    op.drop_index("ix_data_update_job_records_dataset_status", table_name="data_update_job_records")
    op.drop_index("ix_data_update_job_records_job", table_name="data_update_job_records")
    op.drop_table("data_update_job_records")
    op.drop_index("ix_data_update_jobs_created_at", table_name="data_update_jobs")
    op.drop_index("ix_data_update_jobs_status", table_name="data_update_jobs")
    op.drop_table("data_update_jobs")
