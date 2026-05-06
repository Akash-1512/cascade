"""Tests for the Risk Sentinel agent."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from uuid import uuid4

import pytest

from cascade.agents.contracts import RiskAssessment
from cascade.agents.llm import FakeChatModel
from cascade.agents.risk_sentinel import (
    INTERVENTION_THRESHOLD,
    RiskError,
    assess_risk,
)
from cascade.domain.checkin import CheckIn
from cascade.domain.enums import (
    CheckInConfidence,
    KeyResultStatus,
    MetricType,
    ObjectiveStatus,
)
from cascade.domain.okr import KeyResult, Objective, Quarter


def _now() -> datetime:
    return datetime.now(tz=UTC)


def _okr() -> Objective:
    oid = uuid4()
    return Objective(
        id=oid,
        title="Lift weekly active accounts in SMB this quarter",
        owner_id=uuid4(),
        team_id=uuid4(),
        quarter=Quarter(year=2026, quarter=2),
        status=ObjectiveStatus.ACTIVE,
        key_results=[
            KeyResult(
                id=uuid4(),
                objective_id=oid,
                description="Lift weekly active accounts from 200 to 800",
                metric_type=MetricType.NUMBER,
                baseline_value=200,
                target_value=800,
                current_value=300,
                status=KeyResultStatus.AT_RISK,
                owner_id=uuid4(),
                created_at=_now(),
                updated_at=_now(),
            )
        ],
        created_at=_now(),
        updated_at=_now(),
    )


def _checkin(progress: float, confidence: CheckInConfidence, kr_id) -> CheckIn:  # type: ignore[no-untyped-def]
    return CheckIn(
        key_result_id=kr_id,
        progress_value=progress,
        confidence=confidence,
        status=KeyResultStatus.AT_RISK,
        narrative=f"Reached {progress}",
        author_id=uuid4(),
        created_at=_now(),
    )


def _risk_json(
    *,
    score: float = 0.4,
    velocity: str = "on_pace",
    requires: bool = False,
    okr_id: str = "00000000-0000-0000-0000-000000000000",
) -> str:
    return json.dumps(
        {
            "okr_id": okr_id,
            "risk_score": score,
            "velocity_assessment": velocity,
            "factors": [
                {
                    "name": "Velocity slowdown",
                    "severity": "medium",
                    "explanation": "Last two check-ins showed declining weekly delta.",
                }
            ],
            "recommended_interventions": [],
            "requires_intervention": requires,
        }
    )


@pytest.mark.unit
async def test_risk_assessment_returns_structured_result() -> None:
    okr = _okr()
    model = FakeChatModel(responses=[_risk_json(okr_id=str(okr.id))])
    result = await assess_risk(
        okr=okr,
        check_ins=[],
        weeks_elapsed=6,
        model=model,
    )
    assert isinstance(result, RiskAssessment)


@pytest.mark.unit
async def test_intervention_flag_set_when_score_above_threshold() -> None:
    """LLM might forget the flag — we override based on score."""
    okr = _okr()
    payload = _risk_json(score=0.7, velocity="on_pace", requires=False, okr_id=str(okr.id))
    model = FakeChatModel(responses=[payload])
    result = await assess_risk(okr=okr, check_ins=[], weeks_elapsed=6, model=model)
    assert result.risk_score > INTERVENTION_THRESHOLD
    assert result.requires_intervention is True


@pytest.mark.unit
async def test_intervention_flag_set_when_stalled_regardless_of_score() -> None:
    """Stalled velocity overrides low score — the team has stopped progressing."""
    okr = _okr()
    payload = _risk_json(score=0.2, velocity="stalled", requires=False, okr_id=str(okr.id))
    model = FakeChatModel(responses=[payload])
    result = await assess_risk(okr=okr, check_ins=[], weeks_elapsed=6, model=model)
    assert result.requires_intervention is True


@pytest.mark.unit
async def test_intervention_flag_off_when_safe() -> None:
    okr = _okr()
    payload = _risk_json(score=0.2, velocity="on_pace", requires=False, okr_id=str(okr.id))
    model = FakeChatModel(responses=[payload])
    result = await assess_risk(okr=okr, check_ins=[], weeks_elapsed=6, model=model)
    assert result.requires_intervention is False


@pytest.mark.unit
async def test_risk_handles_no_check_ins() -> None:
    okr = _okr()
    model = FakeChatModel(responses=[_risk_json(okr_id=str(okr.id))])
    result = await assess_risk(okr=okr, check_ins=[], weeks_elapsed=2, model=model)
    assert result is not None


@pytest.mark.unit
async def test_risk_with_check_ins_history() -> None:
    okr = _okr()
    kr_id = okr.key_results[0].id
    history = [
        _checkin(progress=300, confidence=CheckInConfidence.LOW, kr_id=kr_id),
        _checkin(progress=290, confidence=CheckInConfidence.MEDIUM, kr_id=kr_id),
        _checkin(progress=270, confidence=CheckInConfidence.HIGH, kr_id=kr_id),
    ]
    model = FakeChatModel(
        responses=[_risk_json(score=0.65, velocity="slowing", requires=True, okr_id=str(okr.id))]
    )
    result = await assess_risk(okr=okr, check_ins=history, weeks_elapsed=8, model=model)
    sent = str(model.call_log[0])
    # All three check-ins should appear in the prompt
    assert "Reached 300" in sent
    assert "Reached 290" in sent
    assert "Reached 270" in sent
    assert result.requires_intervention is True


@pytest.mark.unit
async def test_risk_rejects_invalid_json() -> None:
    okr = _okr()
    model = FakeChatModel(responses=["not json"])
    with pytest.raises(RiskError):
        await assess_risk(okr=okr, check_ins=[], weeks_elapsed=6, model=model)
