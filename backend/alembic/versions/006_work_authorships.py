"""Add work_authorships for publication-specific author affiliations."""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "006_work_authorships"
down_revision = "005_author_profiles"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "work_authorships",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "canonical_work_id",
            sa.String(36),
            sa.ForeignKey("canonical_works.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("provider", sa.String(64), nullable=False),
        sa.Column("provider_author_id", sa.String(256), nullable=True),
        sa.Column(
            "canonical_author_id",
            sa.String(36),
            sa.ForeignKey("canonical_authors.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("display_name", sa.String(512), nullable=False),
        sa.Column("author_position", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("orcid", sa.String(64), nullable=True),
        sa.Column("institutions", sa.JSON(), nullable=True),
        sa.Column("institution_ids", sa.JSON(), nullable=True),
        sa.Column("countries", sa.JSON(), nullable=True),
        sa.Column("raw_metadata", sa.JSON(), nullable=True),
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
            "canonical_work_id",
            "provider",
            "author_position",
            name="uq_work_authorships_work_provider_position",
        ),
    )
    op.create_index(
        "ix_work_authorships_canonical_work_id",
        "work_authorships",
        ["canonical_work_id"],
    )
    op.create_index(
        "ix_work_authorships_provider_author_id",
        "work_authorships",
        ["provider", "provider_author_id"],
    )
    op.create_index(
        "ix_work_authorships_canonical_author_id",
        "work_authorships",
        ["canonical_author_id"],
    )
    op.create_index("ix_work_authorships_orcid", "work_authorships", ["orcid"])


def downgrade() -> None:
    op.drop_table("work_authorships")
