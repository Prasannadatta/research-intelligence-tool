"""Add users table; scope saved searches; track sync actor."""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy import inspect

revision = "011_auth_users"
down_revision = "010_journal_metrics"
branch_labels = None
depends_on = None


def _index_names(inspector, table_name: str) -> set[str]:
    if table_name not in set(inspector.get_table_names()):
        return set()
    return {row["name"] for row in inspector.get_indexes(table_name)}


def _unique_names(inspector, table_name: str) -> set[str]:
    if table_name not in set(inspector.get_table_names()):
        return set()
    return {row["name"] for row in inspector.get_unique_constraints(table_name)}


def upgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)
    table_names = set(inspector.get_table_names())

    if "users" not in table_names:
        op.create_table(
            "users",
            sa.Column("id", sa.String(36), primary_key=True),
            sa.Column("email", sa.String(320), nullable=False),
            sa.Column("normalized_email", sa.String(320), nullable=False),
            sa.Column("password_hash", sa.String(512), nullable=True),
            sa.Column("first_name", sa.String(128), nullable=True),
            sa.Column("last_name", sa.String(128), nullable=True),
            sa.Column("display_name", sa.String(256), nullable=True),
            sa.Column("profile_picture_url", sa.String(1024), nullable=True),
            sa.Column("auth_provider", sa.String(32), nullable=False, server_default="local"),
            sa.Column("google_subject", sa.String(255), nullable=True),
            sa.Column("email_verified", sa.Boolean(), nullable=False, server_default=sa.false()),
            sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
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
            sa.Column("last_login_at", sa.DateTime(timezone=True), nullable=True),
            sa.UniqueConstraint("email", name="uq_users_email"),
            sa.UniqueConstraint("normalized_email", name="uq_users_normalized_email"),
            sa.UniqueConstraint("google_subject", name="uq_users_google_subject"),
        )

    user_indexes = _index_names(inspector, "users")
    if "ix_users_email" not in user_indexes:
        op.create_index("ix_users_email", "users", ["email"])
    if "ix_users_normalized_email" not in user_indexes:
        op.create_index("ix_users_normalized_email", "users", ["normalized_email"])
    if "ix_users_google_subject" not in user_indexes:
        op.create_index("ix_users_google_subject", "users", ["google_subject"])

    # Refresh inspector after users create.
    inspector = inspect(bind)
    table_names = set(inspector.get_table_names())

    if "saved_searches" in table_names:
        columns = {col["name"] for col in inspector.get_columns("saved_searches")}
        if "user_id" not in columns:
            with op.batch_alter_table("saved_searches") as batch_op:
                batch_op.add_column(sa.Column("user_id", sa.String(36), nullable=True))
                batch_op.create_foreign_key(
                    "fk_saved_searches_user_id",
                    "users",
                    ["user_id"],
                    ["id"],
                    ondelete="CASCADE",
                )

        inspector = inspect(bind)
        unique_names = _unique_names(inspector, "saved_searches")
        index_names = _index_names(inspector, "saved_searches")
        # Drop old global uniqueness on canonical_key; uniqueness is per user.
        if "uq_saved_searches_canonical_key" in unique_names:
            with op.batch_alter_table("saved_searches") as batch_op:
                batch_op.drop_constraint("uq_saved_searches_canonical_key", type_="unique")
        if "uq_saved_searches_user_canonical_key" not in unique_names:
            with op.batch_alter_table("saved_searches") as batch_op:
                batch_op.create_unique_constraint(
                    "uq_saved_searches_user_canonical_key",
                    ["user_id", "canonical_key"],
                )
        if "ix_saved_searches_user_id" not in index_names:
            op.create_index("ix_saved_searches_user_id", "saved_searches", ["user_id"])

    if "author_work_sync_state" in table_names:
        columns = {col["name"] for col in inspector.get_columns("author_work_sync_state")}
        if "last_synced_by_user_id" not in columns:
            with op.batch_alter_table("author_work_sync_state") as batch_op:
                batch_op.add_column(
                    sa.Column("last_synced_by_user_id", sa.String(36), nullable=True)
                )
                batch_op.create_foreign_key(
                    "fk_author_work_sync_state_last_synced_by_user_id",
                    "users",
                    ["last_synced_by_user_id"],
                    ["id"],
                    ondelete="SET NULL",
                )
        inspector = inspect(bind)
        sync_indexes = _index_names(inspector, "author_work_sync_state")
        if "ix_author_work_sync_state_last_synced_by" not in sync_indexes:
            op.create_index(
                "ix_author_work_sync_state_last_synced_by",
                "author_work_sync_state",
                ["last_synced_by_user_id"],
            )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)
    table_names = set(inspector.get_table_names())

    if "author_work_sync_state" in table_names:
        sync_indexes = _index_names(inspector, "author_work_sync_state")
        if "ix_author_work_sync_state_last_synced_by" in sync_indexes:
            op.drop_index(
                "ix_author_work_sync_state_last_synced_by",
                table_name="author_work_sync_state",
            )
        columns = {col["name"] for col in inspector.get_columns("author_work_sync_state")}
        if "last_synced_by_user_id" in columns:
            with op.batch_alter_table("author_work_sync_state") as batch_op:
                batch_op.drop_constraint(
                    "fk_author_work_sync_state_last_synced_by_user_id",
                    type_="foreignkey",
                )
                batch_op.drop_column("last_synced_by_user_id")

    if "saved_searches" in table_names:
        inspector = inspect(bind)
        unique_names = _unique_names(inspector, "saved_searches")
        index_names = _index_names(inspector, "saved_searches")
        if "ix_saved_searches_user_id" in index_names:
            op.drop_index("ix_saved_searches_user_id", table_name="saved_searches")
        if "uq_saved_searches_user_canonical_key" in unique_names:
            with op.batch_alter_table("saved_searches") as batch_op:
                batch_op.drop_constraint(
                    "uq_saved_searches_user_canonical_key", type_="unique"
                )
        columns = {col["name"] for col in inspector.get_columns("saved_searches")}
        if "user_id" in columns:
            with op.batch_alter_table("saved_searches") as batch_op:
                batch_op.drop_constraint("fk_saved_searches_user_id", type_="foreignkey")
                batch_op.drop_column("user_id")
        # Restore previous uniqueness (unowned rows only in downgrade path).
        inspector = inspect(bind)
        unique_names = _unique_names(inspector, "saved_searches")
        if "uq_saved_searches_canonical_key" not in unique_names:
            with op.batch_alter_table("saved_searches") as batch_op:
                batch_op.create_unique_constraint(
                    "uq_saved_searches_canonical_key", ["canonical_key"]
                )

    if "users" in table_names:
        for index_name in (
            "ix_users_google_subject",
            "ix_users_normalized_email",
            "ix_users_email",
        ):
            if index_name in _index_names(inspector, "users"):
                op.drop_index(index_name, table_name="users")
        op.drop_table("users")
