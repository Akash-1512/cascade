"""REST API wire schemas.

Distinct from :mod:`cascade.mcp.schemas` so the REST surface and MCP surface
can evolve independently. A change to the JSON shape served over HTTP should
not force a corresponding change to the MCP tool surface and vice-versa,
even when both ultimately call into the same domain types.
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class HealthResponse(BaseModel):
    """Liveness probe response."""

    model_config = ConfigDict(extra="forbid")

    status: Literal["ok", "ready"]
    version: str
    cascade_env: str


# --- OKR schemas -------------------------------------------------------------


class KeyResultResponse(BaseModel):
    """A Key Result over the wire."""

    model_config = ConfigDict(extra="forbid")

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


class ObjectiveResponse(BaseModel):
    """An Objective with its Key Results."""

    model_config = ConfigDict(extra="forbid")

    id: str
    title: str
    description: str | None = None
    quarter: str
    status: Literal["draft", "active", "achieved", "missed", "abandoned"]
    team_id: str
    owner_id: str
    parent_objective_id: str | None = None
    score: float
    key_results: list[KeyResultResponse]
    created_at: datetime
    updated_at: datetime


class ObjectiveSummaryResponse(BaseModel):
    """Compact OKR summary for list responses."""

    model_config = ConfigDict(extra="forbid")

    id: str
    title: str
    quarter: str
    status: Literal["draft", "active", "achieved", "missed", "abandoned"]
    score: float


class OKRListResponse(BaseModel):
    """Top-level wrapper for paginated lists.

    A wrapper rather than a bare array so future additions (page tokens,
    counts, links) don't break clients.
    """

    model_config = ConfigDict(extra="forbid")

    items: list[ObjectiveSummaryResponse]
    count: int


class ScoreBreakdownResponse(BaseModel):
    """Per-KR scoring breakdown for an OKR."""

    model_config = ConfigDict(extra="forbid")

    objective_id: str
    overall_score: float
    key_result_scores: list[dict[str, float | str]]


# --- Decision schemas -------------------------------------------------------


class DecisionResponse(BaseModel):
    """A decision in the causal trail."""

    model_config = ConfigDict(extra="forbid")

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


class DecisionListResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    items: list[DecisionResponse]
    count: int


# --- Organizational learning schemas ----------------------------------------


class LearningResponse(BaseModel):
    """An organizational learning theme."""

    model_config = ConfigDict(extra="forbid")

    id: str
    team_id: str
    quarter: str
    title: str
    description: str
    category: Literal["execution", "planning", "alignment", "estimation", "external", "process"]
    occurrences: int
    affected_okr_ids: list[str]
    supersedes_id: str | None = None
    created_at: datetime


class LearningListResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    items: list[LearningResponse]
    count: int


# --- Mutation request schemas -----------------------------------------------
#
# Distinct from the response types because (a) the server assigns ids and
# timestamps, (b) some fields are server-derived (e.g. KR `score` from
# baseline/current/target), and (c) request validation can be stricter than
# what comes back over the wire (e.g. weights must sum to 1.0 on create but a
# legacy row with 0.99 sum is still served back unchanged on read).


class AlternativeRequest(BaseModel):
    """An alternative considered as part of a Decision."""

    model_config = ConfigDict(extra="forbid")

    option: str = Field(min_length=1, max_length=500)
    reason_rejected: str = Field(min_length=1, max_length=2000)


class EvidenceRequest(BaseModel):
    """A piece of evidence backing a Decision's chosen path."""

    model_config = ConfigDict(extra="forbid")

    source: str = Field(min_length=1, max_length=200)
    claim: str = Field(min_length=1, max_length=2000)
    link: str | None = Field(default=None, max_length=1000)


class DecisionCreateRequest(BaseModel):
    """Payload for ``POST /v1/okrs/{objective_id}/decisions``.

    The objective_id is taken from the path; ``actor_id`` is taken from the
    JWT principal's user_id (in JWT mode) or from the body (in dev mode —
    documented in the runbook).
    """

    model_config = ConfigDict(extra="forbid")

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
    summary: str = Field(min_length=10, max_length=500)
    chosen: str = Field(min_length=1, max_length=2000)
    tradeoff: str | None = Field(default=None, max_length=2000)
    alternatives: list[AlternativeRequest] = Field(default_factory=list, max_length=20)
    evidence: list[EvidenceRequest] = Field(default_factory=list, max_length=20)
    key_result_id: str | None = None
    actor_id: str | None = Field(
        default=None,
        description=(
            "Override the actor_id; defaults to the JWT principal's user_id. "
            "In dev mode the principal's user_id is the bearer token, so this "
            "field is the way to attribute decisions to a specific user."
        ),
    )


class CheckInCreateRequest(BaseModel):
    """Payload for ``POST /v1/key-results/{key_result_id}/checkins``."""

    model_config = ConfigDict(extra="forbid")

    progress_value: float
    confidence: Literal["high", "medium", "low"]
    narrative: str = Field(min_length=1, max_length=4000)
    blockers: str | None = Field(default=None, max_length=2000)
    new_status: (
        Literal["not_started", "on_track", "at_risk", "off_track", "achieved", "missed"] | None
    ) = Field(
        default=None,
        description=(
            "Optional explicit status. If omitted, derived from the confidence "
            "level (high → on_track, medium → at_risk, low → off_track)."
        ),
    )
    author_id: str | None = Field(
        default=None,
        description="Override the author_id; defaults to the JWT principal's user_id.",
    )


class CheckInResponse(BaseModel):
    """A persisted CheckIn on the wire."""

    model_config = ConfigDict(extra="forbid")

    id: str
    key_result_id: str
    progress_value: float
    confidence: Literal["high", "medium", "low"]
    status: Literal["not_started", "on_track", "at_risk", "off_track", "achieved", "missed"]
    narrative: str
    blockers: str | None = None
    author_id: str
    created_at: datetime


class LearningCreateRequest(BaseModel):
    """Payload for ``POST /v1/teams/{team_id}/learnings``."""

    model_config = ConfigDict(extra="forbid")

    quarter: str = Field(pattern=r"^\d{4}Q[1-4]$")
    title: str = Field(min_length=1, max_length=300)
    description: str = Field(min_length=1, max_length=4000)
    category: Literal["execution", "planning", "alignment", "estimation", "external", "process"]
    occurrences: int = Field(ge=1, le=100)
    affected_okr_ids: list[str] = Field(default_factory=list, max_length=50)
    supersedes_id: str | None = None


class KeyResultCreateRequest(BaseModel):
    """A KR inside a new Objective."""

    model_config = ConfigDict(extra="forbid")

    description: str = Field(min_length=1, max_length=500)
    metric_type: Literal["number", "percentage", "currency", "boolean", "milestone"]
    baseline_value: float
    target_value: float
    current_value: float | None = None
    unit: str | None = Field(default=None, max_length=50)
    weight: float = Field(default=1.0, gt=0.0, le=1.0)


class ObjectiveCreateRequest(BaseModel):
    """Payload for ``POST /v1/teams/{team_id}/okrs``.

    A reviewer using this endpoint commits a draft proposal to persistent
    state. Typically these come from ``start_okr_draft`` followed by
    ``resume_okr_draft(decision='commit')`` on the MCP side, then the
    aligned proposal is POSTed here.
    """

    model_config = ConfigDict(extra="forbid")

    title: str = Field(min_length=1, max_length=500)
    description: str | None = Field(default=None, max_length=4000)
    quarter: str = Field(pattern=r"^\d{4}Q[1-4]$")
    owner_id: str
    parent_objective_id: str | None = None
    key_results: list[KeyResultCreateRequest] = Field(min_length=1, max_length=10)
