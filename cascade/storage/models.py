"""SQLAlchemy ORM models.

These are the persistence-layer mirrors of the Pydantic value objects in
``cascade.domain``. They carry the database schema, relationships, and constraints.
Conversion to and from the domain layer happens in ``cascade.storage.repositories``.
"""

from __future__ import annotations

from uuid import UUID, uuid4

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import ENUM as PG_ENUM, JSONB, UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from cascade.domain.enums import (
    CheckInConfidence,
    DecisionEventType,
    KeyResultStatus,
    MetricType,
    ObjectiveStatus,
    UserRole,
)
from cascade.storage import Base, created_at, updated_at, uuid_fk, uuid_pk

# Postgres enum types — defined once so Alembic generates the correct DDL.
_objective_status_enum = PG_ENUM(
    ObjectiveStatus,
    name="objective_status",
    create_type=True,
    values_callable=lambda enum_cls: [member.value for member in enum_cls],
)

_kr_status_enum = PG_ENUM(
    KeyResultStatus,
    name="key_result_status",
    create_type=True,
    values_callable=lambda enum_cls: [member.value for member in enum_cls],
)

_metric_type_enum = PG_ENUM(
    MetricType,
    name="metric_type",
    create_type=True,
    values_callable=lambda enum_cls: [member.value for member in enum_cls],
)

_user_role_enum = PG_ENUM(
    UserRole,
    name="user_role",
    create_type=True,
    values_callable=lambda enum_cls: [member.value for member in enum_cls],
)

_decision_event_enum = PG_ENUM(
    DecisionEventType,
    name="decision_event_type",
    create_type=True,
    values_callable=lambda enum_cls: [member.value for member in enum_cls],
)

_checkin_confidence_enum = PG_ENUM(
    CheckInConfidence,
    name="checkin_confidence",
    create_type=True,
    values_callable=lambda enum_cls: [member.value for member in enum_cls],
)


class TeamORM(Base):
    """A unit that owns OKRs."""

    __tablename__ = "teams"

    id: Mapped[uuid_pk] = mapped_column(default=uuid4)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    slug: Mapped[str] = mapped_column(String(50), nullable=False)
    parent_team_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("teams.id", ondelete="SET NULL"),
        nullable=True,
    )
    created_at: Mapped[created_at]
    updated_at: Mapped[updated_at]

    parent: Mapped[TeamORM | None] = relationship(
        "TeamORM",
        remote_side="TeamORM.id",
        back_populates="children",
    )
    children: Mapped[list[TeamORM]] = relationship(
        "TeamORM", back_populates="parent", cascade="save-update"
    )
    members: Mapped[list[UserORM]] = relationship("UserORM", back_populates="team")
    objectives: Mapped[list[ObjectiveORM]] = relationship("ObjectiveORM", back_populates="team")

    __table_args__ = (UniqueConstraint("slug", name="uq_teams_slug"),)


class UserORM(Base):
    """A person interacting with cascade."""

    __tablename__ = "users"

    id: Mapped[uuid_pk] = mapped_column(default=uuid4)
    email: Mapped[str] = mapped_column(String(320), nullable=False)
    full_name: Mapped[str] = mapped_column(String(200), nullable=False)
    role: Mapped[UserRole] = mapped_column(_user_role_enum, nullable=False)
    team_id: Mapped[uuid_fk] = mapped_column(ForeignKey("teams.id", ondelete="RESTRICT"))
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    password_hash: Mapped[str] = mapped_column(String(200), nullable=False)
    created_at: Mapped[created_at]
    updated_at: Mapped[updated_at]

    team: Mapped[TeamORM] = relationship("TeamORM", back_populates="members")
    owned_objectives: Mapped[list[ObjectiveORM]] = relationship(
        "ObjectiveORM",
        foreign_keys="ObjectiveORM.owner_id",
        back_populates="owner",
    )

    __table_args__ = (UniqueConstraint("email", name="uq_users_email"),)


class ObjectiveORM(Base):
    """A qualitative goal owned by an individual or team."""

    __tablename__ = "objectives"

    id: Mapped[uuid_pk] = mapped_column(default=uuid4)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str | None] = mapped_column(String(2000))
    owner_id: Mapped[uuid_fk] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"))
    team_id: Mapped[uuid_fk] = mapped_column(ForeignKey("teams.id", ondelete="RESTRICT"))
    parent_objective_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("objectives.id", ondelete="SET NULL"),
        nullable=True,
    )
    quarter_year: Mapped[int] = mapped_column(Integer, nullable=False)
    quarter_q: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[ObjectiveStatus] = mapped_column(
        _objective_status_enum, nullable=False, default=ObjectiveStatus.DRAFT
    )
    created_at: Mapped[created_at]
    updated_at: Mapped[updated_at]

    owner: Mapped[UserORM] = relationship(
        "UserORM",
        foreign_keys=[owner_id],
        back_populates="owned_objectives",
    )
    team: Mapped[TeamORM] = relationship("TeamORM", back_populates="objectives")
    parent: Mapped[ObjectiveORM | None] = relationship(
        "ObjectiveORM",
        remote_side="ObjectiveORM.id",
        back_populates="children",
    )
    children: Mapped[list[ObjectiveORM]] = relationship("ObjectiveORM", back_populates="parent")
    key_results: Mapped[list[KeyResultORM]] = relationship(
        "KeyResultORM",
        back_populates="objective",
        cascade="all, delete-orphan",
    )
    decisions: Mapped[list[DecisionORM]] = relationship(
        "DecisionORM",
        back_populates="objective",
        cascade="all, delete-orphan",
    )

    __table_args__ = (
        CheckConstraint(
            "quarter_q BETWEEN 1 AND 4",
            name="quarter_q_range",
        ),
        CheckConstraint(
            "quarter_year BETWEEN 2000 AND 2100",
            name="quarter_year_range",
        ),
        Index(
            "ix_objectives_team_quarter",
            "team_id",
            "quarter_year",
            "quarter_q",
        ),
        Index("ix_objectives_owner", "owner_id"),
    )


class KeyResultORM(Base):
    """A measurable outcome that contributes to an Objective."""

    __tablename__ = "key_results"

    id: Mapped[uuid_pk] = mapped_column(default=uuid4)
    objective_id: Mapped[uuid_fk] = mapped_column(ForeignKey("objectives.id", ondelete="CASCADE"))
    description: Mapped[str] = mapped_column(String(500), nullable=False)
    metric_type: Mapped[MetricType] = mapped_column(_metric_type_enum, nullable=False)
    baseline_value: Mapped[float] = mapped_column(Float, nullable=False)
    target_value: Mapped[float] = mapped_column(Float, nullable=False)
    current_value: Mapped[float] = mapped_column(Float, nullable=False)
    unit: Mapped[str | None] = mapped_column(String(50))
    weight: Mapped[float] = mapped_column(Float, nullable=False, default=1.0)
    status: Mapped[KeyResultStatus] = mapped_column(
        _kr_status_enum, nullable=False, default=KeyResultStatus.NOT_STARTED
    )
    owner_id: Mapped[uuid_fk] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"))
    created_at: Mapped[created_at]
    updated_at: Mapped[updated_at]

    objective: Mapped[ObjectiveORM] = relationship("ObjectiveORM", back_populates="key_results")
    check_ins: Mapped[list[CheckInORM]] = relationship(
        "CheckInORM",
        back_populates="key_result",
        cascade="all, delete-orphan",
        order_by="CheckInORM.created_at.desc()",
    )

    __table_args__ = (
        CheckConstraint("weight > 0", name="weight_positive"),
        Index("ix_key_results_objective", "objective_id"),
    )


class CheckInORM(Base):
    """A point-in-time progress update on a Key Result."""

    __tablename__ = "check_ins"

    id: Mapped[uuid_pk] = mapped_column(default=uuid4)
    key_result_id: Mapped[uuid_fk] = mapped_column(ForeignKey("key_results.id", ondelete="CASCADE"))
    progress_value: Mapped[float] = mapped_column(Float, nullable=False)
    confidence: Mapped[CheckInConfidence] = mapped_column(_checkin_confidence_enum, nullable=False)
    status: Mapped[KeyResultStatus] = mapped_column(_kr_status_enum, nullable=False)
    blockers: Mapped[str | None] = mapped_column(String(2000))
    narrative: Mapped[str] = mapped_column(String(4000), nullable=False)
    author_id: Mapped[uuid_fk] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"))
    created_at: Mapped[created_at]

    key_result: Mapped[KeyResultORM] = relationship("KeyResultORM", back_populates="check_ins")

    __table_args__ = (Index("ix_check_ins_kr_created", "key_result_id", "created_at"),)


class DecisionORM(Base):
    """A captured causal event in the OKR lifecycle."""

    __tablename__ = "decisions"

    id: Mapped[uuid_pk] = mapped_column(default=uuid4)
    event_type: Mapped[DecisionEventType] = mapped_column(_decision_event_enum, nullable=False)
    objective_id: Mapped[uuid_fk] = mapped_column(ForeignKey("objectives.id", ondelete="CASCADE"))
    key_result_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("key_results.id", ondelete="CASCADE"),
        nullable=True,
    )
    summary: Mapped[str] = mapped_column(String(500), nullable=False)
    alternatives: Mapped[list[dict[str, str]]] = mapped_column(JSONB, nullable=False, default=list)
    chosen: Mapped[str] = mapped_column(String(500), nullable=False)
    tradeoff: Mapped[str | None] = mapped_column(String(1000))
    evidence: Mapped[list[dict[str, str]]] = mapped_column(JSONB, nullable=False, default=list)
    actor_id: Mapped[uuid_fk] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"))
    transcript_ref: Mapped[str | None] = mapped_column(String(200))
    created_at: Mapped[created_at]

    objective: Mapped[ObjectiveORM] = relationship("ObjectiveORM", back_populates="decisions")

    __table_args__ = (
        Index("ix_decisions_objective_created", "objective_id", "created_at"),
        Index("ix_decisions_event_type", "event_type"),
    )


class DecisionLinkORM(Base):
    """A typed relationship between two decisions.

    Captures relationships such as ``caused_by``, ``reverses``, ``reinforces`` so the
    Reflector can query "which target reductions cited which retros".
    """

    __tablename__ = "decision_links"

    from_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("decisions.id", ondelete="CASCADE"),
        primary_key=True,
    )
    to_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("decisions.id", ondelete="CASCADE"),
        primary_key=True,
    )
    relation: Mapped[str] = mapped_column(String(50), primary_key=True)
    created_at: Mapped[created_at]

    __table_args__ = (
        CheckConstraint(
            "relation IN ('caused_by', 'reverses', 'reinforces')",
            name="relation_allowed",
        ),
        CheckConstraint("from_id <> to_id", name="no_self_link"),
    )
