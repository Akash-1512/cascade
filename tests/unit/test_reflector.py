"""Tests for the Reflector agent."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from uuid import uuid4

import pytest

from cascade.agents.contracts import ReflectionResult
from cascade.agents.llm import FakeChatModel
from cascade.agents.reflector import ReflectorError, reflect_on_quarter
from cascade.domain.checkin import CheckIn
from cascade.domain.decision import Decision
from cascade.domain.enums import (
    CheckInConfidence,
    DecisionEventType,
    KeyResultStatus,
    MetricType,
    ObjectiveStatus,
)
from cascade.domain.okr import KeyResult, Objective, Quarter


def _now() -> datetime:
    return datetime.now(tz=UTC)


def _make_okr_with_checkins() -> tuple[Objective, list[CheckIn]]:
    okr_id = uuid4()
    kr_id = uuid4()
    okr = Objective(
        id=okr_id,
        title="Reach NPS of 45 across the SMB cohort",
        owner_id=uuid4(),
        team_id=uuid4(),
        quarter=Quarter(year=2026, quarter=2),
        status=ObjectiveStatus.ACHIEVED,
        key_results=[
            KeyResult(
                id=kr_id,
                objective_id=okr_id,
                description="Lift NPS from 32 to 45 in SMB",
                metric_type=MetricType.NUMBER,
                baseline_value=32,
                target_value=45,
                current_value=46,
                status=KeyResultStatus.ACHIEVED,
                owner_id=uuid4(),
                created_at=_now(),
                updated_at=_now(),
            )
        ],
        created_at=_now(),
        updated_at=_now(),
    )
    check_ins = [
        CheckIn(
            key_result_id=kr_id,
            progress_value=42,
            confidence=CheckInConfidence.HIGH,
            status=KeyResultStatus.ON_TRACK,
            narrative="Strong week, reached 42",
            author_id=uuid4(),
            created_at=_now(),
        )
    ]
    return okr, check_ins


def _reflection_json(quarter: str = "2026Q2") -> str:
    return json.dumps(
        {
            "quarter": quarter,
            "summary": "Quarter exceeded targets in SMB segment.",
            "themes": [
                {
                    "title": "Underestimated dependency on data team",
                    "description": "Multiple OKRs slipped because data instrumentation took longer than planned.",
                    "affected_okr_ids": [],
                    "occurrences": 2,
                    "category": "estimation",
                }
            ],
            "wins": ["NPS lifted ahead of plan in SMB"],
            "losses": ["Enterprise expansion KR slipped because of integration cost"],
            "recommendations": [
                "Move check-ins from Friday to Tuesday so the week's actions absorb the feedback"
            ],
        }
    )


@pytest.mark.unit
async def test_reflector_produces_structured_result() -> None:
    okr, check_ins = _make_okr_with_checkins()
    model = FakeChatModel(responses=[_reflection_json()])

    result = await reflect_on_quarter(
        quarter="2026Q2",
        okrs=[okr],
        check_ins=check_ins,
        decisions=[],
        model=model,
    )
    assert isinstance(result, ReflectionResult)
    assert result.quarter == "2026Q2"
    assert len(result.themes) == 1
    assert result.themes[0].category == "estimation"


@pytest.mark.unit
async def test_reflector_rejects_empty_okr_list() -> None:
    model = FakeChatModel(responses=[])
    with pytest.raises(ReflectorError, match="at least one OKR"):
        await reflect_on_quarter(
            quarter="2026Q2",
            okrs=[],
            check_ins=[],
            decisions=[],
            model=model,
        )


@pytest.mark.unit
async def test_reflector_groups_checkins_by_owning_okr() -> None:
    """Check-ins reference KRs; the prompt template needs them grouped by OKR."""
    okr, check_ins = _make_okr_with_checkins()
    model = FakeChatModel(responses=[_reflection_json()])

    await reflect_on_quarter(
        quarter="2026Q2",
        okrs=[okr],
        check_ins=check_ins,
        decisions=[],
        model=model,
    )
    # We can only verify by inspecting the call_log content
    sent = str(model.call_log[0])
    assert "Strong week, reached 42" in sent


@pytest.mark.unit
async def test_reflector_groups_decisions_by_objective_id() -> None:
    okr, _ = _make_okr_with_checkins()
    decision = Decision(
        event_type=DecisionEventType.OBJECTIVE_COMMIT,
        objective_id=okr.id,
        summary="Committed Q2 SMB objective at quarter start",
        chosen="Pursue SMB",
        actor_id=uuid4(),
        created_at=_now(),
    )
    model = FakeChatModel(responses=[_reflection_json()])
    await reflect_on_quarter(
        quarter="2026Q2",
        okrs=[okr],
        check_ins=[],
        decisions=[decision],
        model=model,
    )
    sent = str(model.call_log[0])
    assert "Committed Q2 SMB objective" in sent


@pytest.mark.unit
async def test_reflector_rejects_invalid_json() -> None:
    okr, _ = _make_okr_with_checkins()
    model = FakeChatModel(responses=["not json"])
    with pytest.raises(ReflectorError):
        await reflect_on_quarter(
            quarter="2026Q2",
            okrs=[okr],
            check_ins=[],
            decisions=[],
            model=model,
        )
