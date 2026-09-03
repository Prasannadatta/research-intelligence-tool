"""Add sync completeness fields and analysis job progress_detail."""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy import inspect, text

revision = "015_sync_completeness_and_job_progress"
down_revision = "014_scopus_cited_by"
branch_labels = None
depends_on = None


def _column_names(inspector, table_name: str) -> set[str]:
    if table_name not in inspector.get_table_names():
        return set()
    return {col["name"] for col in inspector.get_columns(table_name)}


def upgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)

    sync_columns = _column_names(inspector, "author_work_sync_state")
    if "author_work_sync_state" in inspector.get_table_names():
        with op.batch_alter_table("author_work_sync_state") as batch_op:
            if "last_successful_synced_at" not in sync_columns:
                batch_op.add_column(
                    sa.Column("last_successful_synced_at", sa.DateTime(timezone=True), nullable=True)
                )
            if "last_attempted_at" not in sync_columns:
                batch_op.add_column(
                    sa.Column("last_attempted_at", sa.DateTime(timezone=True), nullable=True)
                )
            if "error_message" not in sync_columns:
                batch_op.add_column(sa.Column("error_message", sa.Text(), nullable=True))

        # Map legacy success → complete and copy last_synced_at into success timestamp.
        bind.execute(
            text(
                """
                UPDATE author_work_sync_state
                SET status = 'complete'
                WHERE status IN ('success', 'fresh')
                """
            )
        )
        bind.execute(
            text(
                """
                UPDATE author_work_sync_state
                SET last_successful_synced_at = last_synced_at
                WHERE last_successful_synced_at IS NULL
                  AND last_synced_at IS NOT NULL
                  AND status = 'complete'
                """
            )
        )
        bind.execute(
            text(
                """
                UPDATE author_work_sync_state
                SET last_attempted_at = last_synced_at
                WHERE last_attempted_at IS NULL
                  AND last_synced_at IS NOT NULL
                """
            )
        )
        bind.execute(
            text(
                """
                UPDATE author_work_sync_state
                SET status = 'failed'
                WHERE status IN ('provider_failed')
                """
            )
        )
        bind.execute(
            text(
                """
                UPDATE author_work_sync_state
                SET status = 'partial'
                WHERE status IN ('timeout', 'skipped_timeout')
                """
            )
        )

    job_columns = _column_names(inspector, "analysis_jobs")
    if "analysis_jobs" in inspector.get_table_names():
        with op.batch_alter_table("analysis_jobs") as batch_op:
            if "progress_detail" not in job_columns:
                batch_op.add_column(sa.Column("progress_detail", sa.JSON(), nullable=True))
            # Widen stage text for long sync messages.
            batch_op.alter_column(
                "progress_stage",
                existing_type=sa.String(length=128),
                type_=sa.String(length=256),
                existing_nullable=True,
            )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)

    if "analysis_jobs" in inspector.get_table_names():
        job_columns = _column_names(inspector, "analysis_jobs")
        with op.batch_alter_table("analysis_jobs") as batch_op:
            if "progress_detail" in job_columns:
                batch_op.drop_column("progress_detail")
            batch_op.alter_column(
                "progress_stage",
                existing_type=sa.String(length=256),
                type_=sa.String(length=128),
                existing_nullable=True,
            )

    if "author_work_sync_state" in inspector.get_table_names():
        sync_columns = _column_names(inspector, "author_work_sync_state")
        bind.execute(
            text(
                """
                UPDATE author_work_sync_state
                SET status = 'success'
                WHERE status = 'complete'
                """
            )
        )
        bind.execute(
            text(
                """
                UPDATE author_work_sync_state
                SET status = 'provider_failed'
                WHERE status = 'failed'
                """
            )
        )
        with op.batch_alter_table("author_work_sync_state") as batch_op:
            if "error_message" in sync_columns:
                batch_op.drop_column("error_message")
            if "last_attempted_at" in sync_columns:
                batch_op.drop_column("last_attempted_at")
            if "last_successful_synced_at" in sync_columns:
                batch_op.drop_column("last_successful_synced_at")
