"""Initial schema: teams, users, objectives, key_results, check_ins, decisions, decision_links.

Revision ID: 0001_initial_schema
Revises:
Create Date: 2026-05-05
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "0001_initial_schema"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


# ---------------------------------------------------------------------------
# Enum types are defined explicitly so we can drop them cleanly on downgrade.
# ---------------------------------------------------------------------------

OBJECTIVE_STATUS = postgresql.ENUM(
    "draft",
    "active",
    "achieved",
    "missed",
    "abandoned",
    name="objective_status",
    create_type=False,
)

KEY_RESULT_STATUS = postgresql.ENUM(
    "not_started",
    "on_track",
    "at_risk",
    "off_track",
    "achieved",
    "missed",
    name="key_result_status",
    create_type=False,
)

METRIC_TYPE = postgresql.ENUM(
    "number",
    "percentage",
    "currency",
    "boolean",
    "milestone",
    name="metric_type",
    create_type=False,
)

USER_ROLE = postgresql.ENUM(
    "owner",
    "manager",
    "contributor",
    "reader",
    name="user_role",
    create_type=False,
)

DECISION_EVENT_TYPE = postgresql.ENUM(
    "objective_commit",
    "objective_close",
    "objective_reframe",
    "objective_abandon",
    "kr_target_change",
    "kr_descope",
    "kr_replace",
    "risk_intervention",
    name="decision_event_type",
    create_type=False,
)

CHECKIN_CONFIDENCE = postgresql.ENUM(
    "high",
    "medium",
    "low",
    name="checkin_confidence",
    create_type=False,
)


def upgrade() -> None:
    """Create the initial schema."""
    bind = op.get_bind()

    OBJECTIVE_STATUS.create(bind, checkfirst=True)
    KEY_RESULT_STATUS.create(bind, checkfirst=True)
    METRIC_TYPE.create(bind, checkfirst=True)
    USER_ROLE.create(bind, checkfirst=True)
    DECISION_EVENT_TYPE.create(bind, checkfirst=True)
    CHECKIN_CONFIDENCE.create(bind, checkfirst=True)

    op.create_table(
        "teams",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("name", sa.String(length=100), nullable=False),
        sa.Column("slug", sa.String(length=50), nullable=False),
        sa.Column("parent_team_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["parent_team_id"],
            ["teams.id"],
            name="fk_teams_parent_team_id_teams",
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_teams"),
        sa.UniqueConstraint("slug", name="uq_teams_slug"),
    )

    op.create_table(
        "users",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("email", sa.String(length=320), nullable=False),
        sa.Column("full_name", sa.String(length=200), nullable=False),
        sa.Column("role", USER_ROLE, nullable=False),
        sa.Column("team_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("password_hash", sa.String(length=200), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["team_id"],
            ["teams.id"],
            name="fk_users_team_id_teams",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_users"),
        sa.UniqueConstraint("email", name="uq_users_email"),
    )

    op.create_table(
        "objectives",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("title", sa.String(length=200), nullable=False),
        sa.Column("description", sa.String(length=2000), nullable=True),
        sa.Column("owner_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("team_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "parent_objective_id",
            postgresql.UUID(as_uuid=True),
            nullable=True,
        ),
        sa.Column("quarter_year", sa.Integer(), nullable=False),
        sa.Column("quarter_q", sa.Integer(), nullable=False),
        sa.Column(
            "status",
            OBJECTIVE_STATUS,
            nullable=False,
            server_default=sa.text("'draft'::objective_status"),
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "quarter_q BETWEEN 1 AND 4",
            name="quarter_q_range",
        ),
        sa.CheckConstraint(
            "quarter_year BETWEEN 2000 AND 2100",
            name="quarter_year_range",
        ),
        sa.ForeignKeyConstraint(
            ["owner_id"],
            ["users.id"],
            name="fk_objectives_owner_id_users",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["team_id"],
            ["teams.id"],
            name="fk_objectives_team_id_teams",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["parent_objective_id"],
            ["objectives.id"],
            name="fk_objectives_parent_objective_id_objectives",
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_objectives"),
    )
    op.create_index(
        "ix_objectives_team_quarter",
        "objectives",
        ["team_id", "quarter_year", "quarter_q"],
    )
    op.create_index("ix_objectives_owner", "objectives", ["owner_id"])

    op.create_table(
        "key_results",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("objective_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("description", sa.String(length=500), nullable=False),
        sa.Column("metric_type", METRIC_TYPE, nullable=False),
        sa.Column("baseline_value", sa.Float(), nullable=False),
        sa.Column("target_value", sa.Float(), nullable=False),
        sa.Column("current_value", sa.Float(), nullable=False),
        sa.Column("unit", sa.String(length=50), nullable=True),
        sa.Column(
            "weight",
            sa.Float(),
            nullable=False,
            server_default=sa.text("1.0"),
        ),
        sa.Column(
            "status",
            KEY_RESULT_STATUS,
            nullable=False,
            server_default=sa.text("'not_started'::key_result_status"),
        ),
        sa.Column("owner_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint("weight > 0", name="weight_positive"),
        sa.ForeignKeyConstraint(
            ["objective_id"],
            ["objectives.id"],
            name="fk_key_results_objective_id_objectives",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["owner_id"],
            ["users.id"],
            name="fk_key_results_owner_id_users",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_key_results"),
    )
    op.create_index("ix_key_results_objective", "key_results", ["objective_id"])

    op.create_table(
        "check_ins",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("key_result_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("progress_value", sa.Float(), nullable=False),
        sa.Column("confidence", CHECKIN_CONFIDENCE, nullable=False),
        sa.Column("status", KEY_RESULT_STATUS, nullable=False),
        sa.Column("blockers", sa.String(length=2000), nullable=True),
        sa.Column("narrative", sa.String(length=4000), nullable=False),
        sa.Column("author_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["key_result_id"],
            ["key_results.id"],
            name="fk_check_ins_key_result_id_key_results",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["author_id"],
            ["users.id"],
            name="fk_check_ins_author_id_users",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_check_ins"),
    )
    op.create_index(
        "ix_check_ins_kr_created",
        "check_ins",
        ["key_result_id", "created_at"],
    )

    op.create_table(
        "decisions",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("event_type", DECISION_EVENT_TYPE, nullable=False),
        sa.Column("objective_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("key_result_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("summary", sa.String(length=500), nullable=False),
        sa.Column(
            "alternatives",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
        sa.Column("chosen", sa.String(length=500), nullable=False),
        sa.Column("tradeoff", sa.String(length=1000), nullable=True),
        sa.Column(
            "evidence",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
        sa.Column("actor_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("transcript_ref", sa.String(length=200), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["objective_id"],
            ["objectives.id"],
            name="fk_decisions_objective_id_objectives",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["key_result_id"],
            ["key_results.id"],
            name="fk_decisions_key_result_id_key_results",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["actor_id"],
            ["users.id"],
            name="fk_decisions_actor_id_users",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_decisions"),
    )
    op.create_index(
        "ix_decisions_objective_created",
        "decisions",
        ["objective_id", "created_at"],
    )
    op.create_index("ix_decisions_event_type", "decisions", ["event_type"])

    op.create_table(
        "decision_links",
        sa.Column("from_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("to_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("relation", sa.String(length=50), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "relation IN ('caused_by', 'reverses', 'reinforces')",
            name="relation_allowed",
        ),
        sa.CheckConstraint(
            "from_id <> to_id",
            name="no_self_link",
        ),
        sa.ForeignKeyConstraint(
            ["from_id"],
            ["decisions.id"],
            name="fk_decision_links_from_id_decisions",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["to_id"],
            ["decisions.id"],
            name="fk_decision_links_to_id_decisions",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint(
            "from_id",
            "to_id",
            "relation",
            name="pk_decision_links",
        ),
    )


def downgrade() -> None:
    """Drop everything created in :func:`upgrade`."""
    op.drop_table("decision_links")
    op.drop_index("ix_decisions_event_type", table_name="decisions")
    op.drop_index("ix_decisions_objective_created", table_name="decisions")
    op.drop_table("decisions")
    op.drop_index("ix_check_ins_kr_created", table_name="check_ins")
    op.drop_table("check_ins")
    op.drop_index("ix_key_results_objective", table_name="key_results")
    op.drop_table("key_results")
    op.drop_index("ix_objectives_owner", table_name="objectives")
    op.drop_index("ix_objectives_team_quarter", table_name="objectives")
    op.drop_table("objectives")
    op.drop_table("users")
    op.drop_table("teams")

    bind = op.get_bind()
    CHECKIN_CONFIDENCE.drop(bind, checkfirst=True)
    DECISION_EVENT_TYPE.drop(bind, checkfirst=True)
    USER_ROLE.drop(bind, checkfirst=True)
    METRIC_TYPE.drop(bind, checkfirst=True)
    KEY_RESULT_STATUS.drop(bind, checkfirst=True)
    OBJECTIVE_STATUS.drop(bind, checkfirst=True)
