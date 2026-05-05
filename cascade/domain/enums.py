"""Enumerations used across the cascade domain.

These values are persisted to the database, surfaced through the API, and rendered in
the UI. Adding a value is a forward-compatible change. Removing or renaming one is a
breaking change and requires a migration plus an ADR.
"""

from __future__ import annotations

from enum import StrEnum


class ObjectiveStatus(StrEnum):
    """Lifecycle states for an Objective.

    The transitions are:

    ``DRAFT`` --commit--> ``ACTIVE``
    ``ACTIVE`` --close--> ``ACHIEVED`` | ``MISSED`` | ``ABANDONED``

    ``ACHIEVED`` and ``MISSED`` are the two healthy terminal states. ``ABANDONED`` is
    reserved for OKRs explicitly de-scoped — distinct from missed because the team
    chose to stop, rather than failed to deliver.
    """

    DRAFT = "draft"
    ACTIVE = "active"
    ACHIEVED = "achieved"
    MISSED = "missed"
    ABANDONED = "abandoned"


class KeyResultStatus(StrEnum):
    """Health states for a Key Result during its active life.

    Distinct from ``ObjectiveStatus`` because KRs have an additional dimension —
    confidence in delivery — that we surface to managers.
    """

    NOT_STARTED = "not_started"
    ON_TRACK = "on_track"
    AT_RISK = "at_risk"
    OFF_TRACK = "off_track"
    ACHIEVED = "achieved"
    MISSED = "missed"


class MetricType(StrEnum):
    """How a Key Result is measured.

    ``NUMBER`` and ``PERCENTAGE`` are scored linearly between baseline and target.
    ``CURRENCY`` is treated as ``NUMBER`` with a unit. ``BOOLEAN`` collapses to 0 or 1.
    ``MILESTONE`` is scored as the fraction of declared milestones reached.
    """

    NUMBER = "number"
    PERCENTAGE = "percentage"
    CURRENCY = "currency"
    BOOLEAN = "boolean"
    MILESTONE = "milestone"


class DecisionEventType(StrEnum):
    """The kinds of decisions cascade captures in the causal graph.

    See ADR-0002 for why this is a structured enum rather than free text.
    """

    OBJECTIVE_COMMIT = "objective_commit"
    OBJECTIVE_CLOSE = "objective_close"
    OBJECTIVE_REFRAME = "objective_reframe"
    OBJECTIVE_ABANDON = "objective_abandon"
    KR_TARGET_CHANGE = "kr_target_change"
    KR_DESCOPE = "kr_descope"
    KR_REPLACE = "kr_replace"
    RISK_INTERVENTION = "risk_intervention"


class UserRole(StrEnum):
    """Authorisation roles for the cascade API.

    Distinct from team membership — a ``MANAGER`` may belong to one team but be able to
    review OKRs across child teams. Roles compose with team scope, they don't replace
    it.
    """

    OWNER = "owner"
    MANAGER = "manager"
    CONTRIBUTOR = "contributor"
    READER = "reader"


class CheckInConfidence(StrEnum):
    """The author's stated confidence in hitting the target.

    Captured separately from the numeric progress score because confidence and
    progress can disagree — a KR at 0.6 progress with low confidence is a different
    story than one at 0.6 with high confidence.
    """

    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"
