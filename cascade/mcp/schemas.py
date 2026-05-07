"""Wire-format schemas for the MCP tools.

These types describe what MCP clients send and receive. They are intentionally
distinct from :mod:`cascade.domain` so the protocol surface can evolve without
touching domain code, and so MCP clients see strings (UUIDs as strings, datetimes
as ISO 8601) rather than the Python-only types our internal code uses.

FastMCP introspects the type hints on tool functions and emits JSON schema. Every
parameter and return type below has been chosen for clean MCP rendering — no
``Optional[X]`` where ``X | None`` works, no ``List[X]`` where ``list[X]`` works,
and no Pydantic ``ConfigDict(extra='forbid')`` on returns because that confuses
some MCP clients' permissive parsers.
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

# --- OKR tool schemas -------------------------------------------------------


class KeyResultView(BaseModel):
    """A Key Result rendered for MCP clients."""

    id: str
    description: str
    metric_type: Literal["number", "percentage", "currency", "boolean", "milestone"]
    baseline_value: float
    target_value: float
    current_value: float
    unit: str | None = None
    weight: float
    status: Literal["not_started", "on_track", "at_risk", "off_track", "achieved", "missed"]
    score: float = Field(description="Derived score in [0.0, 1.0].")


class ObjectiveView(BaseModel):
    """An Objective rendered for MCP clients."""

    id: str
    title: str
    description: str | None = None
    quarter: str = Field(description="Planning period as 'YYYYQ[1-4]'.")
    status: Literal["draft", "active", "achieved", "missed", "abandoned"]
    team_id: str
    owner_id: str
    parent_objective_id: str | None = None
    score: float = Field(description="Aggregate score across the Objective's KRs.")
    key_results: list[KeyResultView]
    created_at: datetime
    updated_at: datetime


class ObjectiveSummary(BaseModel):
    """Compact OKR view for list responses where full key results would be noisy."""

    id: str
    title: str
    quarter: str
    status: Literal["draft", "active", "achieved", "missed", "abandoned"]
    score: float


# --- Decision tool schemas --------------------------------------------------


class DecisionView(BaseModel):
    """A Decision rendered for MCP clients.

    The ``alternatives`` and ``evidence`` arrays are returned as plain dicts
    rather than nested Pydantic types — keeps the JSON schema simpler at the
    edge.
    """

    id: str
    event_type: Literal[
        "objective_commit",
        "objective_close",
        "objective_reframe",
        "objective_abandon",
        "kr_target_change",
        "kr_descope",
        "kr_replace",
        "risk_intervention",
    ]
    objective_id: str
    key_result_id: str | None = None
    summary: str
    alternatives: list[dict[str, str]]
    chosen: str
    tradeoff: str | None = None
    evidence: list[dict[str, str]]
    actor_id: str
    created_at: datetime


# --- Draft / score tool schemas ---------------------------------------------


class DraftedKeyResult(BaseModel):
    """A drafted Key Result returned to MCP callers."""

    description: str
    metric_type: Literal["number", "percentage", "currency", "boolean", "milestone"]
    baseline_value: float
    target_value: float
    current_value: float | None = None
    unit: str | None = None
    weight: float = 1.0


class DraftedObjective(BaseModel):
    """A drafted Objective with its Key Results, before persistence."""

    title: str
    description: str | None = None
    key_results: list[DraftedKeyResult]


class DraftResult(BaseModel):
    """Result of the ``draft_okr`` tool.

    Includes both the proposal and the critique so the caller can decide
    whether to commit, revise, or escalate.
    """

    proposal: DraftedObjective
    critique_verdict: Literal["pass", "needs_revision", "reject"]
    critique_overall_score: float
    critique_suggestions: list[str]
    iterations: int


class ScoreResult(BaseModel):
    """Per-KR scoring breakdown for an existing OKR."""

    objective_id: str
    overall_score: float
    key_result_scores: list[dict[str, float | str]]


# --- Check-in tool schemas --------------------------------------------------


class CheckInResult(BaseModel):
    """Acknowledgement returned after a check-in is logged."""

    check_in_id: str
    key_result_id: str
    new_progress_value: float
    new_status: Literal["not_started", "on_track", "at_risk", "off_track", "achieved", "missed"]
    coaching_message: str


# --- Risk and alignment tool schemas ---------------------------------------


class RiskFactorView(BaseModel):
    name: str
    severity: Literal["low", "medium", "high"]
    explanation: str


class RiskAssessmentView(BaseModel):
    objective_id: str
    risk_score: float
    velocity_assessment: Literal["ahead", "on_pace", "slowing", "stalled"]
    factors: list[RiskFactorView]
    recommended_interventions: list[str]
    requires_intervention: bool


class AlignmentConflictView(BaseModel):
    peer_okr_id: str | None = None
    peer_title: str
    conflict_type: Literal["resource", "metric", "scope", "timing"]
    description: str
    severity: Literal["info", "warning", "blocking"]


class AlignmentResultView(BaseModel):
    objective_id: str
    vertical_score: float
    vertical_reasoning: str
    conflicts: list[AlignmentConflictView]
    verdict: Literal["aligned", "needs_review", "blocked"]
    suggestions: list[str]


# --- HITL drafting tool schemas ---------------------------------------------


class HitlConflictView(BaseModel):
    """A single alignment conflict surfaced when a draft pauses for human review."""

    conflict_type: Literal["scope", "resource", "priority", "metric", "timeline"]
    description: str
    severity: Literal["info", "warning", "blocking"]
    peer_title: str | None = None


class HitlPauseInfo(BaseModel):
    """Information about a paused HITL draft, returned to the MCP client.

    Carries everything the client needs to surface the pause to a human and
    collect a decision: the proposal so far, the alignment verdict and any
    blocking conflicts, the iteration count, and the reason the supervisor
    routed to the human node.
    """

    status: Literal["paused"] = "paused"
    reason: str
    iteration_count: int
    proposal: DraftedObjective | None = None
    alignment_verdict: Literal["aligned", "needs_review", "blocked"] | None = None
    alignment_summary: str | None = None
    conflicts: list[HitlConflictView] = []
    suggestions: list[str] = []


class HitlCompleteInfo(BaseModel):
    """Final state of a HITL draft that completed (aligned or terminally rejected)."""

    status: Literal["completed"] = "completed"
    proposal: DraftedObjective
    alignment_verdict: Literal["aligned", "needs_review", "blocked"]
    alignment_summary: str | None = None
    conflicts: list[HitlConflictView] = []
    iteration_count: int


class StartOkrDraftResult(BaseModel):
    """Result of the ``start_okr_draft`` tool.

    The ``state`` field is one of :class:`HitlPauseInfo` or
    :class:`HitlCompleteInfo` distinguished by ``state.status``. The
    ``thread_id`` is opaque to the client and must be passed back to
    ``resume_okr_draft`` to continue a paused run.
    """

    thread_id: str
    state: HitlPauseInfo | HitlCompleteInfo


class ResumeOkrDraftResult(BaseModel):
    """Result of the ``resume_okr_draft`` tool.

    Same shape as :class:`StartOkrDraftResult`. The same draft can pause
    again on a subsequent revision (the user asked to revise; the next
    drafter pass produced a proposal that the Aligner blocked again);
    callers handle that by calling ``resume_okr_draft`` again with the same
    ``thread_id``.
    """

    thread_id: str
    state: HitlPauseInfo | HitlCompleteInfo
