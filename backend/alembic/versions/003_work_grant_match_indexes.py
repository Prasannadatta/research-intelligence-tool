"""Add lookup indexes for work_grant_matches grant suggestions."""

from __future__ import annotations

from alembic import op


revision = "003_work_grant_match_indexes"
down_revision = "002_work_persistence"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_index(
        "ix_work_grant_matches_provider",
        "work_grant_matches",
        ["provider"],
    )
    op.create_index(
        "ix_work_grant_matches_normalized_grant_number",
        "work_grant_matches",
        ["normalized_grant_number"],
    )
    op.create_index(
        "ix_work_grant_matches_provider_normalized_grant_number",
        "work_grant_matches",
        ["provider", "normalized_grant_number"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_work_grant_matches_provider_normalized_grant_number",
        table_name="work_grant_matches",
    )
    op.drop_index(
        "ix_work_grant_matches_normalized_grant_number",
        table_name="work_grant_matches",
    )
    op.drop_index(
        "ix_work_grant_matches_provider",
        table_name="work_grant_matches",
    )
