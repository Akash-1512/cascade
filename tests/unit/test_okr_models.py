"""Tests for OKR domain model validation and computed properties."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

import pytest
from pydantic import ValidationError

from cascade.domain.enums import KeyResultStatus, MetricType, ObjectiveStatus
from cascade.domain.okr import KeyResult, Objective, Quarter


def _now() -> datetime:
    return datetime.now(tz=UTC)


def _make_kr(
    *,
    metric_type: MetricType = MetricType.NUMBER,
    baseline: float = 0,
    current: float = 50,
    target: float = 100,
    weight: float = 1.0,
) -> KeyResult:
    return KeyResult(
        objective_id=uuid4(),
        description="Increase weekly active users from baseline to target",
        metric_type=metric_type,
        baseline_value=baseline,
        target_value=target,
        current_value=current,
        weight=weight,
        owner_id=uuid4(),
        created_at=_now(),
        updated_at=_now(),
    )


class TestQuarter:
    @pytest.mark.unit
    def test_from_string_valid(self) -> None:
        q = Quarter.from_string("2026Q2")
        assert q.year == 2026
        assert q.quarter == 2

    @pytest.mark.unit
    def test_from_string_lowercase_q(self) -> None:
        q = Quarter.from_string("2026q3")
        assert q.year == 2026
        assert q.quarter == 3

    @pytest.mark.unit
    @pytest.mark.parametrize("bad", ["", "26Q2", "2026-Q2", "2026Q5", "2026Q0", "2026X1"])
    def test_from_string_invalid(self, bad: str) -> None:
        with pytest.raises((ValueError, ValidationError)):
            Quarter.from_string(bad)

    @pytest.mark.unit
    def test_str_round_trip(self) -> None:
        q = Quarter(year=2026, quarter=4)
        assert str(q) == "2026Q4"
        assert Quarter.from_string(str(q)) == q


class TestKeyResultValidation:
    @pytest.mark.unit
    def test_valid_number_metric(self) -> None:
        kr = _make_kr()
        assert kr.score == 0.5

    @pytest.mark.unit
    def test_description_too_short_rejected(self) -> None:
        with pytest.raises(ValidationError):
            KeyResult(
                objective_id=uuid4(),
                description="short",
                metric_type=MetricType.NUMBER,
                baseline_value=0,
                target_value=100,
                current_value=0,
                owner_id=uuid4(),
                created_at=_now(),
                updated_at=_now(),
            )

    @pytest.mark.unit
    def test_zero_weight_rejected(self) -> None:
        with pytest.raises(ValidationError):
            _make_kr(weight=0.0)

    @pytest.mark.unit
    def test_negative_weight_rejected(self) -> None:
        with pytest.raises(ValidationError):
            _make_kr(weight=-1.0)

    @pytest.mark.unit
    def test_boolean_with_non_binary_value_rejected(self) -> None:
        with pytest.raises(ValidationError, match="boolean metric must be 0 or 1"):
            _make_kr(metric_type=MetricType.BOOLEAN, baseline=0, current=0.5, target=1)

    @pytest.mark.unit
    def test_percentage_above_100_rejected(self) -> None:
        with pytest.raises(ValidationError, match=r"percentage metric must be in \[0, 100\]"):
            _make_kr(metric_type=MetricType.PERCENTAGE, baseline=0, current=50, target=110)

    @pytest.mark.unit
    def test_percentage_below_zero_rejected(self) -> None:
        with pytest.raises(ValidationError, match=r"percentage metric must be in \[0, 100\]"):
            _make_kr(metric_type=MetricType.PERCENTAGE, baseline=-5, current=50, target=80)

    @pytest.mark.unit
    def test_milestone_negative_target_rejected(self) -> None:
        with pytest.raises(ValidationError, match="milestone target_value must be positive"):
            _make_kr(metric_type=MetricType.MILESTONE, baseline=0, current=0, target=0)

    @pytest.mark.unit
    def test_milestone_nonzero_baseline_rejected(self) -> None:
        with pytest.raises(ValidationError, match="milestone baseline_value must be 0"):
            _make_kr(metric_type=MetricType.MILESTONE, baseline=1, current=2, target=5)

    @pytest.mark.unit
    def test_milestone_current_out_of_range(self) -> None:
        with pytest.raises(ValidationError, match="milestone current_value out of range"):
            _make_kr(metric_type=MetricType.MILESTONE, baseline=0, current=6, target=5)


class TestKeyResultScore:
    @pytest.mark.unit
    def test_score_property_uses_dispatcher(self) -> None:
        kr = _make_kr(baseline=0, current=70, target=100)
        assert kr.score == 0.7

    @pytest.mark.unit
    def test_score_with_milestone(self) -> None:
        kr = _make_kr(metric_type=MetricType.MILESTONE, baseline=0, current=3, target=4)
        assert kr.score == 0.75


class TestObjective:
    @pytest.mark.unit
    def test_default_status_is_draft(self) -> None:
        obj = Objective(
            title="Become the most loved tool in our category",
            owner_id=uuid4(),
            team_id=uuid4(),
            quarter=Quarter(year=2026, quarter=2),
            created_at=_now(),
            updated_at=_now(),
        )
        assert obj.status == ObjectiveStatus.DRAFT

    @pytest.mark.unit
    def test_title_whitespace_only_rejected(self) -> None:
        with pytest.raises(ValidationError, match="cannot be whitespace"):
            Objective(
                title="          ",
                owner_id=uuid4(),
                team_id=uuid4(),
                quarter=Quarter(year=2026, quarter=2),
                created_at=_now(),
                updated_at=_now(),
            )

    @pytest.mark.unit
    def test_title_too_short_rejected(self) -> None:
        with pytest.raises(ValidationError):
            Objective(
                title="Win",
                owner_id=uuid4(),
                team_id=uuid4(),
                quarter=Quarter(year=2026, quarter=2),
                created_at=_now(),
                updated_at=_now(),
            )

    @pytest.mark.unit
    def test_score_aggregates_key_results(self) -> None:
        oid = uuid4()
        krs = [
            KeyResult(
                objective_id=oid,
                description=f"Key result number {i} description text",
                metric_type=MetricType.NUMBER,
                baseline_value=0,
                target_value=100,
                current_value=current,
                weight=1.0,
                status=KeyResultStatus.ON_TRACK,
                owner_id=uuid4(),
                created_at=_now(),
                updated_at=_now(),
            )
            for i, current in enumerate([50, 80, 100], start=1)
        ]
        obj = Objective(
            id=oid,
            title="Reach product-market fit in the SMB segment",
            owner_id=uuid4(),
            team_id=uuid4(),
            quarter=Quarter(year=2026, quarter=2),
            key_results=krs,
            created_at=_now(),
            updated_at=_now(),
        )
        # mean of 0.5, 0.8, 1.0 = 0.7666...
        assert obj.score == pytest.approx((0.5 + 0.8 + 1.0) / 3)

    @pytest.mark.unit
    def test_score_empty_key_results_is_zero(self) -> None:
        obj = Objective(
            title="Reach product-market fit in the SMB segment",
            owner_id=uuid4(),
            team_id=uuid4(),
            quarter=Quarter(year=2026, quarter=2),
            created_at=_now(),
            updated_at=_now(),
        )
        assert obj.score == 0.0
