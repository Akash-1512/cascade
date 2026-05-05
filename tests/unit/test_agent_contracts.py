"""Tests for agent contract types."""

from __future__ import annotations

import pytest

from cascade.agents.contracts import (
    CritiqueResult,
    DimensionScore,
    HumanInterrupt,
    ProposedKeyResult,
    ProposedObjective,
)
from cascade.domain.enums import MetricType


def _kr(**kwargs: object) -> ProposedKeyResult:
    defaults: dict[str, object] = {
        "description": "Increase weekly active accounts from baseline to target",
        "metric_type": MetricType.NUMBER,
        "baseline_value": 200.0,
        "target_value": 800.0,
    }
    defaults.update(kwargs)
    return ProposedKeyResult(**defaults)  # type: ignore[arg-type]


def _critique(**kwargs: object) -> CritiqueResult:
    """Build a CritiqueResult with sane defaults."""
    defaults: dict[str, object] = {
        "specificity": DimensionScore(score=0.8, reasoning="concrete and segmented"),
        "measurability": DimensionScore(
            score=0.85, reasoning="quantified with explicit baselines and targets"
        ),
        "ambition": DimensionScore(
            score=0.75, reasoning="targets feel uncomfortable but achievable"
        ),
        "structure": DimensionScore(
            score=0.9, reasoning="three KRs, qualitative O, measurable KRs"
        ),
        "vague_phrases": [],
        "verdict": "pass",
        "suggestions": [],
    }
    defaults.update(kwargs)
    return CritiqueResult(**defaults)  # type: ignore[arg-type]


@pytest.mark.unit
def test_proposed_objective_with_minimum_fields() -> None:
    obj = ProposedObjective(title="Reach product-market fit in SMB", key_results=[_kr()])
    assert obj.title.startswith("Reach product-market fit")
    assert len(obj.key_results) == 1


@pytest.mark.unit
def test_proposed_objective_caps_key_results_at_ten() -> None:
    """Schema-level cap is generous; the agent layer trims to 5."""
    krs = [_kr() for _ in range(10)]
    obj = ProposedObjective(title="A title that meets the minimum length", key_results=krs)
    assert len(obj.key_results) == 10


@pytest.mark.unit
def test_critique_overall_score_is_unweighted_mean() -> None:
    critique = _critique(
        specificity=DimensionScore(score=0.6, reasoning="r"),
        measurability=DimensionScore(score=0.8, reasoning="r"),
        ambition=DimensionScore(score=1.0, reasoning="r"),
        structure=DimensionScore(score=0.4, reasoning="r"),
    )
    assert critique.overall_score == pytest.approx((0.6 + 0.8 + 1.0 + 0.4) / 4)


@pytest.mark.unit
def test_dimension_score_clamped_to_unit() -> None:
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        DimensionScore(score=1.1, reasoning="impossible")
    with pytest.raises(ValidationError):
        DimensionScore(score=-0.1, reasoning="impossible")


@pytest.mark.unit
def test_human_interrupt_reasons_are_constrained() -> None:
    from pydantic import ValidationError

    HumanInterrupt(reason="iteration_cap_reached")
    HumanInterrupt(reason="fundamental_reject")
    with pytest.raises(ValidationError):
        HumanInterrupt(reason="not-a-real-reason")  # type: ignore[arg-type]
