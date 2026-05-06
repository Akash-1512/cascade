"""Shared types for the cascade eval suite.

The suite produces a single :class:`EvalReport` per run, written to JSON for
artifact upload and threshold checking. ``check_thresholds.py`` reads the same
report and gates merges in CI.

Eval modules are responsible for one metric family each (drafting, critic
agreement, retrieval, red team) and return :class:`MetricResult` instances. The
runner aggregates them into the report.
"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class CaseResult(BaseModel):
    """Per-case outcome inside a metric.

    Captured so failures can be inspected individually after a CI run — the
    artifact upload preserves this so a reviewer can pull exactly the cases
    that regressed.
    """

    model_config = ConfigDict(extra="forbid")

    case_id: str
    passed: bool
    score: float = Field(ge=0.0, le=1.0)
    expected: str | float | None = None
    actual: str | float | None = None
    notes: str | None = None


class MetricResult(BaseModel):
    """The aggregated outcome of a single metric family."""

    model_config = ConfigDict(extra="forbid")

    name: str
    score: float = Field(ge=0.0, le=1.0)
    threshold: float = Field(ge=0.0, le=1.0)
    cases: list[CaseResult] = Field(default_factory=list)
    metadata: dict[str, object] = Field(default_factory=dict)

    @property
    def passed(self) -> bool:
        """Did this metric clear its threshold?"""
        return self.score >= self.threshold

    def model_dump_summary(self) -> dict[str, object]:
        """Compact summary for the threshold checker's PR comment."""
        return {
            "score": self.score,
            "threshold": self.threshold,
            "passed": self.passed,
            "cases_total": len(self.cases),
            "cases_passed": sum(1 for c in self.cases if c.passed),
        }


class EvalReport(BaseModel):
    """The full eval-run report. Serialised to ``eval_results.json``."""

    model_config = ConfigDict(extra="forbid")

    run_id: str
    started_at: datetime
    finished_at: datetime
    cascade_version: str
    metrics: dict[str, MetricResult]

    @property
    def all_passed(self) -> bool:
        """Did every metric clear its threshold?"""
        return all(m.passed for m in self.metrics.values())
