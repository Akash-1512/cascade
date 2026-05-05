"""Unit tests for the SQLAlchemy ORM model declarations.

These tests verify the metadata, relationships, and constraints without standing up a
database. Tests that require an actual database live under ``tests/integration/``.
"""

from __future__ import annotations

import pytest

from cascade.storage import Base
from cascade.storage.models import (
    CheckInORM,
    DecisionLinkORM,
    DecisionORM,
    KeyResultORM,
    ObjectiveORM,
    TeamORM,
    UserORM,
)


@pytest.mark.unit
def test_all_tables_registered() -> None:
    """All seven domain tables are present in the metadata."""
    expected = {
        "teams",
        "users",
        "objectives",
        "key_results",
        "check_ins",
        "decisions",
        "decision_links",
    }
    assert set(Base.metadata.tables.keys()) == expected


@pytest.mark.unit
def test_team_has_self_referential_foreign_key() -> None:
    """``parent_team_id`` references the ``teams.id`` column."""
    fk = next(iter(TeamORM.__table__.c.parent_team_id.foreign_keys))
    assert fk.column.table.name == "teams"
    assert fk.ondelete == "SET NULL"


@pytest.mark.unit
def test_objective_has_parent_self_reference() -> None:
    """OKR cascading is enabled by ``parent_objective_id``."""
    fk = next(iter(ObjectiveORM.__table__.c.parent_objective_id.foreign_keys))
    assert fk.column.table.name == "objectives"
    assert fk.ondelete == "SET NULL"


@pytest.mark.unit
def test_key_result_cascades_from_objective() -> None:
    """Deleting an objective deletes its key results."""
    fk = next(iter(KeyResultORM.__table__.c.objective_id.foreign_keys))
    assert fk.column.table.name == "objectives"
    assert fk.ondelete == "CASCADE"


@pytest.mark.unit
def test_check_in_cascades_from_key_result() -> None:
    """Deleting a key result deletes its check-ins."""
    fk = next(iter(CheckInORM.__table__.c.key_result_id.foreign_keys))
    assert fk.column.table.name == "key_results"
    assert fk.ondelete == "CASCADE"


@pytest.mark.unit
def test_decision_objective_fk_cascades() -> None:
    """Deleting an objective deletes its decision history."""
    fk = next(
        fk
        for fk in DecisionORM.__table__.c.objective_id.foreign_keys
        if fk.column.table.name == "objectives"
    )
    assert fk.ondelete == "CASCADE"


@pytest.mark.unit
def test_decision_actor_fk_restricts() -> None:
    """Cannot delete a user who has authored decisions."""
    fk = next(iter(DecisionORM.__table__.c.actor_id.foreign_keys))
    assert fk.column.table.name == "users"
    assert fk.ondelete == "RESTRICT"


@pytest.mark.unit
def test_user_email_unique() -> None:
    """Email is enforced unique."""
    constraints = {c.name for c in UserORM.__table__.constraints}
    assert "uq_users_email" in constraints


@pytest.mark.unit
def test_team_slug_unique() -> None:
    """Slug is enforced unique."""
    constraints = {c.name for c in TeamORM.__table__.constraints}
    assert "uq_teams_slug" in constraints


@pytest.mark.unit
def test_decision_link_self_link_forbidden() -> None:
    """A decision cannot link to itself — enforced at the database."""
    constraints = {c.name for c in DecisionLinkORM.__table__.constraints}
    assert "ck_decision_links_no_self_link" in constraints


@pytest.mark.unit
def test_decision_link_relation_constrained() -> None:
    """Only allowed relation values are accepted."""
    constraints = {c.name for c in DecisionLinkORM.__table__.constraints}
    assert "ck_decision_links_relation_allowed" in constraints


@pytest.mark.unit
def test_objective_quarter_constraints() -> None:
    """Quarter values are constrained to valid ranges at the database."""
    constraints = {c.name for c in ObjectiveORM.__table__.constraints}
    assert "ck_objectives_quarter_q_range" in constraints
    assert "ck_objectives_quarter_year_range" in constraints


@pytest.mark.unit
def test_key_result_weight_constraint() -> None:
    """KR weight is positive at the database."""
    constraints = {c.name for c in KeyResultORM.__table__.constraints}
    assert "ck_key_results_weight_positive" in constraints


@pytest.mark.unit
def test_objective_team_quarter_index_present() -> None:
    """Common query pattern (team + quarter) is indexed."""
    indexes = {idx.name for idx in ObjectiveORM.__table__.indexes}
    assert "ix_objectives_team_quarter" in indexes


@pytest.mark.unit
def test_check_in_kr_created_index_present() -> None:
    """Check-in chronological retrieval is indexed."""
    indexes = {idx.name for idx in CheckInORM.__table__.indexes}
    assert "ix_check_ins_kr_created" in indexes


@pytest.mark.unit
def test_decision_objective_index_present() -> None:
    """Decision-by-objective retrieval is indexed."""
    indexes = {idx.name for idx in DecisionORM.__table__.indexes}
    assert "ix_decisions_objective_created" in indexes
