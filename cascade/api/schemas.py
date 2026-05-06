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
