"""Add organizational_learnings table.

Revision ID: 0002_organizational_learnings
Revises: 0001_initial_schema
Create Date: 2026-05-06
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic
revision = "0002_organizational_learnings"
down_revision = "0001_initial_schema"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "organizational_learnings",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "team_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("teams.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("quarter", sa.String(6), nullable=False),
        sa.Column("title", sa.String(200), nullable=False),
        sa.Column("description", sa.String(2000), nullable=False),
        sa.Column("category", sa.String(20), nullable=False),
        sa.Column("occurrences", sa.Integer, nullable=False),
        sa.Column(
            "affected_okr_ids",
            postgresql.JSONB,
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
        sa.Column(
            "supersedes_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("organizational_learnings.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "category IN ('execution', 'planning', 'alignment', 'estimation', "
            "'external', 'process')",
            name="category_allowed",
        ),
        sa.CheckConstraint(
            r"quarter ~ '^\d{4}Q[1-4]$'",
            name="quarter_format",
        ),
        sa.CheckConstraint("occurrences >= 1", name="occurrences_positive"),
    )
    op.create_index(
        "ix_org_learnings_team_quarter",
        "organizational_learnings",
        ["team_id", "quarter"],
    )
    op.create_index(
        "ix_org_learnings_category",
        "organizational_learnings",
        ["category"],
    )


def downgrade() -> None:
    op.drop_index("ix_org_learnings_category", table_name="organizational_learnings")
    op.drop_index("ix_org_learnings_team_quarter", table_name="organizational_learnings")
    op.drop_table("organizational_learnings")
