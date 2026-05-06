"""Contracts that agents pass to each other.

These are the wire types between agents — distinct from :mod:`cascade.domain` because:

- A *proposed* OKR has no UUIDs, no timestamps, no owner. It is an unsigned draft.
- A *critique* is a structured judgement, not a value object that gets persisted.
- Splitting these from the domain keeps the persistence schema independent of agent
  evolution. Adding a new critique dimension does not require a database migration.

When the Supervisor decides to commit a proposal, it converts ``ProposedObjective`` →
:class:`cascade.domain.okr.ObjectiveCreate` at the boundary.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from cascade.domain.enums import MetricType


class ProposedKeyResult(BaseModel):
    """A drafted Key Result before it has been persisted.

    Mirrors :class:`cascade.domain.okr.KeyResult` minus the persistence concerns
    (id, owner, timestamps). Validators are looser here because the Drafter produces
    candidates the Critic then evaluates — overly tight gates here would prevent the
    Critic from ever seeing the bad drafts that are precisely what it is meant to
    catch.
    """

    model_config = ConfigDict(extra="forbid")

    description: str = Field(min_length=1, max_length=500)
    metric_type: MetricType
    baseline_value: float
    target_value: float
    current_value: float | None = None
    unit: str | None = Field(default=None, max_length=50)
    weight: float = Field(default=1.0, gt=0.0, le=10.0)


class ProposedObjective(BaseModel):
    """A drafted Objective with its proposed Key Results."""

    model_config = ConfigDict(extra="forbid")

    title: str = Field(min_length=1, max_length=200)
    description: str | None = Field(default=None, max_length=2000)
    key_results: list[ProposedKeyResult] = Field(default_factory=list, max_length=10)


# --- Critique types ---------------------------------------------------------

CritiqueVerdict = Literal["pass", "needs_revision", "reject"]
"""The Critic's overall verdict.

- ``pass`` — proposal is good enough to move forward to alignment review
- ``needs_revision`` — proposal has fixable issues; Drafter loops with critique
- ``reject`` — proposal has fundamental problems; escalate to human
"""


class DimensionScore(BaseModel):
    """Score for a single critique dimension."""

    model_config = ConfigDict(extra="forbid")

    score: float = Field(ge=0.0, le=1.0)
    reasoning: str = Field(min_length=1, max_length=1000)


class CritiqueResult(BaseModel):
    """The Critic's structured judgement on a proposed OKR.

    Scores are in ``[0.0, 1.0]``. The overall score is the equally-weighted average
    of the four dimensions; we compute it from the parts rather than asking the LLM
    for a separate global score, because forcing arithmetic consistency reduces
    variance on borderline cases.
    """

    model_config = ConfigDict(extra="forbid")

    specificity: DimensionScore = Field(
        description="Is the Objective concrete enough to know whether you are working on it?"
    )
    measurability: DimensionScore = Field(
        description="Are KRs quantified with explicit targets and timeframes?"
    )
    ambition: DimensionScore = Field(
        description="Would a 0.7 score be a real stretch, or comfortably achievable?"
    )
    structure: DimensionScore = Field(
        description="Does the proposal follow OKR conventions — qualitative O, "
        "measurable KRs, KR count between 2 and 5?"
    )
    vague_phrases: list[str] = Field(
        default_factory=list,
        max_length=20,
        description="Verbatim spans from the proposal that are vague, weasel-worded, "
        "or unfalsifiable.",
    )
    verdict: CritiqueVerdict
    suggestions: list[str] = Field(
        default_factory=list,
        max_length=10,
        description="Concrete suggestions the Drafter should apply on the next iteration.",
    )

    @property
    def overall_score(self) -> float:
        """Equally-weighted mean of the four dimension scores."""
        dims = [self.specificity, self.measurability, self.ambition, self.structure]
        return sum(d.score for d in dims) / len(dims)


class DraftIteration(BaseModel):
    """A single (proposal, critique) pair captured for the iteration history.

    Stored on the agent state so the Drafter can see what previous attempts looked
    like and avoid producing the same flawed draft twice in a row.
    """

    model_config = ConfigDict(extra="forbid")

    proposal: ProposedObjective
    critique: CritiqueResult
    iteration: int = Field(ge=1)


class HumanInterrupt(BaseModel):
    """Marker that the graph is paused waiting on human input.

    The graph cannot resume until a human responds. The ``reason`` is surfaced to
    the UI; the ``payload`` is whatever the agent needs to render the decision the
    human is being asked to make.
    """

    model_config = ConfigDict(extra="forbid")

    reason: Literal[
        "iteration_cap_reached",
        "fundamental_reject",
        "alignment_conflict",
        "target_change",
        "kr_descope",
        "risk_intervention",
    ]
    payload: dict[str, object] = Field(default_factory=dict)


# --- Aligner contracts ------------------------------------------------------


class AlignmentConflict(BaseModel):
    """A specific conflict between the proposal and a peer or parent OKR."""

    model_config = ConfigDict(extra="forbid")

    peer_okr_id: str | None = Field(
        default=None,
        description="UUID of the peer OKR if the conflict is horizontal; None for vertical.",
    )
    peer_title: str
    conflict_type: Literal["resource", "metric", "scope", "timing"]
    description: str = Field(min_length=1, max_length=500)
    severity: Literal["info", "warning", "blocking"]


class AlignmentResult(BaseModel):
    """The Aligner's structured judgement on alignment.

    ``vertical_score`` measures how well the proposal ladders up to its parent
    Objective. ``conflicts`` lists horizontal collisions with peer OKRs. A
    proposal can pass alignment with informational conflicts but not blocking
    ones.
    """

    model_config = ConfigDict(extra="forbid")

    vertical_score: float = Field(ge=0.0, le=1.0)
    vertical_reasoning: str = Field(min_length=1, max_length=1000)
    conflicts: list[AlignmentConflict] = Field(default_factory=list, max_length=20)
    verdict: Literal["aligned", "needs_review", "blocked"]
    suggestions: list[str] = Field(default_factory=list, max_length=10)


# --- Check-in Coach contracts -----------------------------------------------


class CheckInUpdate(BaseModel):
    """A proposed update derived from a check-in conversation.

    The Coach extracts these from free-text user messages. Anything that changes
    a target or descopes a KR triggers an HITL interrupt — the user must
    explicitly confirm.
    """

    model_config = ConfigDict(extra="forbid")

    key_result_id: str
    new_progress_value: float | None = None
    new_target_value: float | None = None
    new_status: (
        Literal["not_started", "on_track", "at_risk", "off_track", "achieved", "missed"] | None
    ) = None
    confidence: Literal["high", "medium", "low"]
    blockers: str | None = Field(default=None, max_length=2000)
    narrative: str = Field(min_length=1, max_length=4000)
    requires_confirmation: bool = Field(
        default=False,
        description="True when the update changes a target — Coach interrupts.",
    )


class CoachResponse(BaseModel):
    """The Coach's structured output from a check-in turn."""

    model_config = ConfigDict(extra="forbid")

    updates: list[CheckInUpdate] = Field(default_factory=list, max_length=10)
    coaching_message: str = Field(min_length=1, max_length=4000)
    follow_up_questions: list[str] = Field(default_factory=list, max_length=5)


# --- Reflector contracts ----------------------------------------------------


class ReflectionTheme(BaseModel):
    """A pattern the Reflector clusters out of quarterly check-ins."""

    model_config = ConfigDict(extra="forbid")

    title: str = Field(min_length=1, max_length=200)
    description: str = Field(min_length=1, max_length=2000)
    affected_okr_ids: list[str] = Field(default_factory=list, max_length=20)
    occurrences: int = Field(ge=1, description="Number of check-ins exhibiting this theme.")
    category: Literal["execution", "planning", "alignment", "estimation", "external", "process"]


class ReflectionResult(BaseModel):
    """The Reflector's quarterly retrospective output."""

    model_config = ConfigDict(extra="forbid")

    quarter: str = Field(pattern=r"^\d{4}Q[1-4]$")
    summary: str = Field(min_length=1, max_length=4000)
    themes: list[ReflectionTheme] = Field(default_factory=list, max_length=10)
    wins: list[str] = Field(default_factory=list, max_length=10)
    losses: list[str] = Field(default_factory=list, max_length=10)
    recommendations: list[str] = Field(default_factory=list, max_length=10)


# --- Risk Sentinel contracts ------------------------------------------------


class RiskFactor(BaseModel):
    """A single contributor to elevated risk on an Objective or KR."""

    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=100)
    severity: Literal["low", "medium", "high"]
    explanation: str = Field(min_length=1, max_length=500)


class RiskAssessment(BaseModel):
    """The Risk Sentinel's structured prediction."""

    model_config = ConfigDict(extra="forbid")

    okr_id: str
    risk_score: float = Field(
        ge=0.0,
        le=1.0,
        description="Probability of missing the target by quarter end. 0=safe, 1=certain miss.",
    )
    velocity_assessment: Literal["ahead", "on_pace", "slowing", "stalled"]
    factors: list[RiskFactor] = Field(default_factory=list, max_length=10)
    recommended_interventions: list[str] = Field(default_factory=list, max_length=5)
    requires_intervention: bool = Field(
        default=False,
        description="True when risk_score crosses the configured threshold.",
    )
