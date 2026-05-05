"""Tests for the OKR scoring functions."""

from __future__ import annotations

import pytest

from cascade.domain.enums import MetricType
from cascade.domain.scoring import (
    score_boolean,
    score_key_result,
    score_linear,
    score_milestone,
    score_objective,
)


class TestScoreLinear:
    """Linear scoring covers the majority of KRs."""

    @pytest.mark.unit
    def test_baseline_is_zero(self) -> None:
        """Halfway between 0 and 100 scores 0.5."""
        assert score_linear(baseline=0, current=50, target=100) == 0.5

    @pytest.mark.unit
    def test_at_target_scores_one(self) -> None:
        assert score_linear(baseline=0, current=100, target=100) == 1.0

    @pytest.mark.unit
    def test_at_baseline_scores_zero(self) -> None:
        assert score_linear(baseline=20, current=20, target=100) == 0.0

    @pytest.mark.unit
    def test_decreasing_target(self) -> None:
        """Reducing churn from 8% to 4% — at 6% we are halfway."""
        assert score_linear(baseline=8, current=6, target=4) == 0.5

    @pytest.mark.unit
    def test_below_baseline_clamps_to_zero(self) -> None:
        """Regressing below the starting point still floors at 0."""
        assert score_linear(baseline=50, current=30, target=100) == 0.0

    @pytest.mark.unit
    def test_above_target_clamps_to_one(self) -> None:
        """Overachievement caps at 1.0 — Google convention."""
        assert score_linear(baseline=0, current=120, target=100) == 1.0

    @pytest.mark.unit
    def test_baseline_equals_target_achieved(self) -> None:
        """A 'maintain X' KR scores 1.0 when current is at or above target."""
        assert score_linear(baseline=100, current=100, target=100) == 1.0
        assert score_linear(baseline=100, current=101, target=100) == 1.0

    @pytest.mark.unit
    def test_baseline_equals_target_below(self) -> None:
        """A 'maintain X' KR scores 0 when current is below target."""
        assert score_linear(baseline=100, current=99, target=100) == 0.0


class TestScoreBoolean:
    @pytest.mark.unit
    def test_true_scores_one(self) -> None:
        assert score_boolean(True) == 1.0

    @pytest.mark.unit
    def test_false_scores_zero(self) -> None:
        assert score_boolean(False) == 0.0


class TestScoreMilestone:
    @pytest.mark.unit
    def test_partial_completion(self) -> None:
        assert score_milestone(milestones_completed=3, milestones_total=4) == 0.75

    @pytest.mark.unit
    def test_zero_completed(self) -> None:
        assert score_milestone(milestones_completed=0, milestones_total=5) == 0.0

    @pytest.mark.unit
    def test_all_completed(self) -> None:
        assert score_milestone(milestones_completed=5, milestones_total=5) == 1.0

    @pytest.mark.unit
    def test_zero_total_raises(self) -> None:
        with pytest.raises(ValueError, match="milestones_total must be positive"):
            score_milestone(milestones_completed=0, milestones_total=0)

    @pytest.mark.unit
    def test_negative_total_raises(self) -> None:
        with pytest.raises(ValueError, match="milestones_total must be positive"):
            score_milestone(milestones_completed=0, milestones_total=-3)

    @pytest.mark.unit
    def test_completed_exceeds_total_raises(self) -> None:
        with pytest.raises(ValueError, match="milestones_completed must be within"):
            score_milestone(milestones_completed=6, milestones_total=5)

    @pytest.mark.unit
    def test_negative_completed_raises(self) -> None:
        with pytest.raises(ValueError, match="milestones_completed must be within"):
            score_milestone(milestones_completed=-1, milestones_total=5)


class TestScoreKeyResult:
    """Dispatcher tests covering each metric type."""

    @pytest.mark.unit
    def test_dispatches_number_to_linear(self) -> None:
        assert score_key_result(MetricType.NUMBER, 0, 70, 100) == 0.7

    @pytest.mark.unit
    def test_dispatches_currency_to_linear(self) -> None:
        assert score_key_result(MetricType.CURRENCY, 100_000, 150_000, 200_000) == 0.5

    @pytest.mark.unit
    def test_dispatches_percentage_to_linear(self) -> None:
        assert score_key_result(MetricType.PERCENTAGE, 20, 35, 50) == 0.5

    @pytest.mark.unit
    def test_dispatches_boolean(self) -> None:
        assert score_key_result(MetricType.BOOLEAN, 0, 1, 1) == 1.0
        assert score_key_result(MetricType.BOOLEAN, 0, 0, 1) == 0.0

    @pytest.mark.unit
    def test_dispatches_milestone(self) -> None:
        assert score_key_result(MetricType.MILESTONE, 0, 2, 5) == 0.4


class TestScoreObjective:
    """Objective scoring is a weighted aggregate."""

    @pytest.mark.unit
    def test_equal_weights(self) -> None:
        result = score_objective([(1.0, 0.7), (1.0, 0.5), (1.0, 0.9)])
        assert result == pytest.approx(0.7)

    @pytest.mark.unit
    def test_unequal_weights(self) -> None:
        # 2x weight on a 1.0 KR, 1x weight on a 0.0 KR -> 0.667
        result = score_objective([(2.0, 1.0), (1.0, 0.0)])
        assert result == pytest.approx(2 / 3)

    @pytest.mark.unit
    def test_empty_returns_zero(self) -> None:
        assert score_objective([]) == 0.0

    @pytest.mark.unit
    def test_single_kr(self) -> None:
        assert score_objective([(1.0, 0.4)]) == 0.4

    @pytest.mark.unit
    def test_normalisation_with_unit_weights(self) -> None:
        """Weights don't have to sum to 1.0 — they are normalised."""
        a = score_objective([(1.0, 0.5), (1.0, 1.0)])
        b = score_objective([(0.5, 0.5), (0.5, 1.0)])
        assert a == pytest.approx(b)
