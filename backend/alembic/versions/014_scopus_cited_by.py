"""Add Scopus cited-by cache, citing works, and citation links."""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy import inspect

revision = "014_scopus_cited_by"
down_revision = "013_analysis_jobs"
branch_labels = None
depends_on = None


def _index_names(inspector, table_name: str) -> set[str]:
    if table_name not in inspector.get_table_names():
        return set()
    return {row["name"] for row in inspector.get_indexes(table_name)}


def upgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)
    table_names = set(inspector.get_table_names())

    if "scopus_cited_by_sync" not in table_names:
        op.create_table(
            "scopus_cited_by_sync",
            sa.Column("id", sa.String(36), primary_key=True),
            sa.Column("canonical_work_id", sa.String(36), nullable=False),
            sa.Column("scopus_id", sa.String(64), nullable=True),
            sa.Column("eid", sa.String(128), nullable=True),
            sa.Column("citedby_count", sa.Integer(), nullable=True),
            sa.Column("status", sa.String(32), nullable=False, server_default="never"),
            sa.Column("last_synced_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column(
                "fetched_result_count",
                sa.Integer(),
                nullable=False,
                server_default="0",
            ),
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
            sa.ForeignKeyConstraint(
                ["canonical_work_id"],
                ["canonical_works.id"],
                ondelete="CASCADE",
            ),
            sa.UniqueConstraint(
                "canonical_work_id",
                name="uq_scopus_cited_by_sync_canonical_work",
            ),
        )
    indexes = _index_names(inspect(bind), "scopus_cited_by_sync")
    if "ix_scopus_cited_by_sync_status_expires" not in indexes:
        op.create_index(
            "ix_scopus_cited_by_sync_status_expires",
            "scopus_cited_by_sync",
            ["status", "expires_at"],
        )
    if "ix_scopus_cited_by_sync_scopus_id" not in indexes:
        op.create_index(
            "ix_scopus_cited_by_sync_scopus_id",
            "scopus_cited_by_sync",
            ["scopus_id"],
        )

    inspector = inspect(bind)
    table_names = set(inspector.get_table_names())
    if "scopus_citing_works" not in table_names:
        op.create_table(
            "scopus_citing_works",
            sa.Column("id", sa.String(36), primary_key=True),
            sa.Column("scopus_id", sa.String(64), nullable=True),
            sa.Column("eid", sa.String(128), nullable=True),
            sa.Column("doi", sa.String(512), nullable=True),
            sa.Column("normalized_doi", sa.String(512), nullable=True),
            sa.Column("title", sa.String(2048), nullable=True),
            sa.Column("cover_date", sa.String(32), nullable=True),
            sa.Column("publication_year", sa.Integer(), nullable=True),
            sa.Column("source_title", sa.String(1024), nullable=True),
            sa.Column("affiliations", sa.JSON(), nullable=True),
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
            sa.UniqueConstraint("scopus_id", name="uq_scopus_citing_works_scopus_id"),
            sa.UniqueConstraint("eid", name="uq_scopus_citing_works_eid"),
        )
    indexes = _index_names(inspect(bind), "scopus_citing_works")
    if "ix_scopus_citing_works_normalized_doi" not in indexes:
        op.create_index(
            "ix_scopus_citing_works_normalized_doi",
            "scopus_citing_works",
            ["normalized_doi"],
        )
    if "ix_scopus_citing_works_publication_year" not in indexes:
        op.create_index(
            "ix_scopus_citing_works_publication_year",
            "scopus_citing_works",
            ["publication_year"],
        )

    inspector = inspect(bind)
    table_names = set(inspector.get_table_names())
    if "scopus_citation_links" not in table_names:
        op.create_table(
            "scopus_citation_links",
            sa.Column("id", sa.String(36), primary_key=True),
            sa.Column("citing_work_id", sa.String(36), nullable=False),
            sa.Column("cited_canonical_work_id", sa.String(36), nullable=False),
            sa.Column("cited_scopus_id", sa.String(64), nullable=True),
            sa.ForeignKeyConstraint(
                ["citing_work_id"],
                ["scopus_citing_works.id"],
                ondelete="CASCADE",
            ),
            sa.ForeignKeyConstraint(
                ["cited_canonical_work_id"],
                ["canonical_works.id"],
                ondelete="CASCADE",
            ),
            sa.UniqueConstraint(
                "citing_work_id",
                "cited_canonical_work_id",
                name="uq_scopus_citation_links_citing_cited",
            ),
        )
    indexes = _index_names(inspect(bind), "scopus_citation_links")
    if "ix_scopus_citation_links_cited_canonical" not in indexes:
        op.create_index(
            "ix_scopus_citation_links_cited_canonical",
            "scopus_citation_links",
            ["cited_canonical_work_id"],
        )
    if "ix_scopus_citation_links_cited_scopus_id" not in indexes:
        op.create_index(
            "ix_scopus_citation_links_cited_scopus_id",
            "scopus_citation_links",
            ["cited_scopus_id"],
        )


def downgrade() -> None:
    op.drop_index(
        "ix_scopus_citation_links_cited_scopus_id",
        table_name="scopus_citation_links",
    )
    op.drop_index(
        "ix_scopus_citation_links_cited_canonical",
        table_name="scopus_citation_links",
    )
    op.drop_table("scopus_citation_links")
    op.drop_index(
        "ix_scopus_citing_works_publication_year",
        table_name="scopus_citing_works",
    )
    op.drop_index(
        "ix_scopus_citing_works_normalized_doi",
        table_name="scopus_citing_works",
    )
    op.drop_table("scopus_citing_works")
    op.drop_index(
        "ix_scopus_cited_by_sync_scopus_id",
        table_name="scopus_cited_by_sync",
    )
    op.drop_index(
        "ix_scopus_cited_by_sync_status_expires",
        table_name="scopus_cited_by_sync",
    )
    op.drop_table("scopus_cited_by_sync")
