"""Add author_work_sync_state.resume_cursor for partial crawl resume."""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy import inspect

revision = "016_sync_resume_cursor"
down_revision = "015_sync_completeness_and_job_progress"
branch_labels = None
depends_on = None


def _column_names(inspector, table_name: str) -> set[str]:
    if table_name not in inspector.get_table_names():
        return set()
    return {col["name"] for col in inspector.get_columns(table_name)}


def upgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)
    if "author_work_sync_state" not in inspector.get_table_names():
        return
    columns = _column_names(inspector, "author_work_sync_state")
    if "resume_cursor" in columns:
        return
    with op.batch_alter_table("author_work_sync_state") as batch_op:
        batch_op.add_column(sa.Column("resume_cursor", sa.String(length=512), nullable=True))


def downgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)
    if "author_work_sync_state" not in inspector.get_table_names():
        return
    columns = _column_names(inspector, "author_work_sync_state")
    if "resume_cursor" not in columns:
        return
    with op.batch_alter_table("author_work_sync_state") as batch_op:
        batch_op.drop_column("resume_cursor")
