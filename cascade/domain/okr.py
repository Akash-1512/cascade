"""Objective and Key Result domain models.

The two core OKR primitives. Objectives are qualitative — they describe what the team
is trying to achieve. Key Results are quantitative — they describe how progress is
measured. An Objective without measurable Key Results is a slogan; a Key Result
without an Objective is a metric divorced from intent.
"""

from __future__ import annotations

from datetime import datetime
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from cascade.domain.enums import KeyResultStatus, MetricType, ObjectiveStatus
from cascade.domain.scoring import score_key_result, score_objective


class Quarter(BaseModel):
    """A planning period, of the form ``YYYYQ[1-4]``.

    A simple value type so the rest of the code never has to parse strings.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    year: int = Field(ge=2000, le=2100)
    quarter: int = Field(ge=1, le=4)

    @classmethod
    def from_string(cls, value: str) -> Quarter:
        """Parse from ``"2026Q2"`` style.

        Raises:
            ValueError: when ``value`` does not match the expected pattern.
        """
        if len(value) != 6 or value[4].upper() != "Q":
            raise ValueError(f"invalid quarter string: {value!r}")
        return cls(year=int(value[:4]), quarter=int(value[5]))

    def __str__(self) -> str:
        return f"{self.year}Q{self.quarter}"


class KeyResult(BaseModel):
    """A measurable outcome that contributes to an Objective.

    Each Key Result has a metric type, a baseline (where we started), a target (where
    we want to be), and a current value (where we are now). The score is derived from
    these three numbers and the metric type — it is never stored independently.

    ``weight`` is used when aggregating Key Results into an Objective score. By
    default all KRs are equally weighted; teams that want to emphasise particular
    outcomes can adjust.
    """

    model_config = ConfigDict(extra="forbid")

    id: UUID = Field(default_factory=uuid4)
    objective_id: UUID
    description: str = Field(min_length=10, max_length=500)
    metric_type: MetricType
    baseline_value: float
    target_value: float
    current_value: float
    unit: str | None = Field(default=None, max_length=50)
    weight: float = Field(default=1.0, gt=0.0, le=10.0)
    status: KeyResultStatus = KeyResultStatus.NOT_STARTED
    owner_id: UUID
    created_at: datetime
    updated_at: datetime

    @model_validator(mode="after")
    def _validate_targets(self) -> KeyResult:
        """Enforce metric-type-specific target constraints."""
        if self.metric_type == MetricType.BOOLEAN:
            for name, value in (
                ("baseline_value", self.baseline_value),
                ("target_value", self.target_value),
                ("current_value", self.current_value),
            ):
                if value not in (0.0, 1.0):
                    raise ValueError(f"{name} for boolean metric must be 0 or 1, got {value}")
        if self.metric_type == MetricType.PERCENTAGE:
            for name, value in (
                ("baseline_value", self.baseline_value),
                ("target_value", self.target_value),
                ("current_value", self.current_value),
            ):
                if not 0.0 <= value <= 100.0:
                    raise ValueError(
                        f"{name} for percentage metric must be in [0, 100], got {value}"
                    )
        if self.metric_type == MetricType.MILESTONE:
            if self.target_value <= 0:
                raise ValueError("milestone target_value must be positive")
            if self.baseline_value != 0:
                raise ValueError("milestone baseline_value must be 0")
            if not (0 <= self.current_value <= self.target_value):
                raise ValueError("milestone current_value out of range")
        return self

    @property
    def score(self) -> float:
        """Current score in ``[0.0, 1.0]``, derived from baseline, current, target."""
        return score_key_result(
            self.metric_type,
            self.baseline_value,
            self.current_value,
            self.target_value,
        )


class Objective(BaseModel):
    """A qualitative goal owned by an individual or team.

    ``parent_objective_id`` enables OKR cascading — child objectives ladder up to a
    parent, typically owned by a parent team. Cycles are forbidden at the database
    level (see migration).
    """

    model_config = ConfigDict(extra="forbid")

    id: UUID = Field(default_factory=uuid4)
    title: str = Field(min_length=10, max_length=200)
    description: str | None = Field(default=None, max_length=2000)
    owner_id: UUID
    team_id: UUID
    parent_objective_id: UUID | None = None
    quarter: Quarter
    status: ObjectiveStatus = ObjectiveStatus.DRAFT
    key_results: list[KeyResult] = Field(default_factory=list)
    created_at: datetime
    updated_at: datetime

    @field_validator("title")
    @classmethod
    def _title_not_just_whitespace(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("title cannot be whitespace-only")
        return value.strip()

    @property
    def score(self) -> float:
        """Aggregate score across this Objective's Key Results."""
        return score_objective([(kr.weight, kr.score) for kr in self.key_results])


class KeyResultCreate(BaseModel):
    """Payload for creating a Key Result."""

    model_config = ConfigDict(extra="forbid")

    description: str = Field(min_length=10, max_length=500)
    metric_type: MetricType
    baseline_value: float
    target_value: float
    current_value: float | None = None
    unit: str | None = Field(default=None, max_length=50)
    weight: float = Field(default=1.0, gt=0.0, le=10.0)


class ObjectiveCreate(BaseModel):
    """Payload for creating an Objective with its Key Results."""

    model_config = ConfigDict(extra="forbid")

    title: str = Field(min_length=10, max_length=200)
    description: str | None = Field(default=None, max_length=2000)
    team_id: UUID
    parent_objective_id: UUID | None = None
    quarter: Quarter
    key_results: list[KeyResultCreate] = Field(default_factory=list, max_length=10)
