"""Add journal_metrics cache for Scopus Serial Title enrichment."""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy import inspect

revision = "010_journal_metrics"
down_revision = "009_data_update_jobs"
branch_labels = None
depends_on = None


def _index_names(inspector, table_name: str) -> set[str]:
    return {row["name"] for row in inspector.get_indexes(table_name)}


def upgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)
    table_names = set(inspector.get_table_names())

    if "journal_metrics" not in table_names:
        op.create_table(
            "journal_metrics",
            sa.Column("id", sa.String(36), primary_key=True),
            sa.Column("normalized_issn", sa.String(16), nullable=False),
            sa.Column("print_issn", sa.String(16), nullable=True),
            sa.Column("electronic_issn", sa.String(16), nullable=True),
            sa.Column("journal_name", sa.String(1024), nullable=True),
            sa.Column("scopus_source_id", sa.String(64), nullable=True),
            sa.Column("scopus_url", sa.String(1024), nullable=True),
            sa.Column("citescore", sa.Float(), nullable=True),
            sa.Column("citescore_year", sa.Integer(), nullable=True),
            sa.Column("sjr", sa.Float(), nullable=True),
            sa.Column("sjr_year", sa.Integer(), nullable=True),
            sa.Column("snip", sa.Float(), nullable=True),
            sa.Column("snip_year", sa.Integer(), nullable=True),
            sa.Column("source", sa.String(32), nullable=False, server_default="scopus"),
            sa.Column("status", sa.String(32), nullable=False, server_default="success"),
            sa.Column(
                "retrieved_at",
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
            sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("raw_metadata", sa.JSON(), nullable=True),
            sa.UniqueConstraint("normalized_issn", name="uq_journal_metrics_normalized_issn"),
        )
    indexes = _index_names(inspector, "journal_metrics")
    if "ix_journal_metrics_scopus_source_id" not in indexes:
        op.create_index(
            "ix_journal_metrics_scopus_source_id",
            "journal_metrics",
            ["scopus_source_id"],
        )
    if "ix_journal_metrics_status_expires" not in indexes:
        op.create_index(
            "ix_journal_metrics_status_expires",
            "journal_metrics",
            ["status", "expires_at"],
        )

    inspector = inspect(bind)
    table_names = set(inspector.get_table_names())
    if "journal_issn_aliases" not in table_names:
        op.create_table(
            "journal_issn_aliases",
            sa.Column("id", sa.String(36), primary_key=True),
            sa.Column("normalized_issn", sa.String(16), nullable=False),
            sa.Column("journal_metrics_id", sa.String(36), nullable=False),
            sa.ForeignKeyConstraint(
                ["journal_metrics_id"],
                ["journal_metrics.id"],
                ondelete="CASCADE",
            ),
            sa.UniqueConstraint(
                "normalized_issn", name="uq_journal_issn_aliases_normalized_issn"
            ),
        )
        op.create_index(
            "ix_journal_issn_aliases_journal_metrics_id",
            "journal_issn_aliases",
            ["journal_metrics_id"],
        )


def downgrade() -> None:
    op.drop_index(
        "ix_journal_issn_aliases_journal_metrics_id",
        table_name="journal_issn_aliases",
    )
    op.drop_table("journal_issn_aliases")
    op.drop_index("ix_journal_metrics_status_expires", table_name="journal_metrics")
    op.drop_index("ix_journal_metrics_scopus_source_id", table_name="journal_metrics")
    op.drop_table("journal_metrics")
