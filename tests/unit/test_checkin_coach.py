"""Tests for the Check-in Coach agent."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from uuid import uuid4

import pytest

from cascade.agents.checkin_coach import CoachError, run_checkin
from cascade.agents.contracts import CoachResponse
from cascade.agents.llm import FakeChatModel
from cascade.domain.enums import KeyResultStatus, MetricType, ObjectiveStatus
from cascade.domain.okr import KeyResult, Objective, Quarter


def _now() -> datetime:
    return datetime.now(tz=UTC)


def _objective() -> Objective:
    oid = uuid4()
    return Objective(
        id=oid,
        title="Reach product-market fit in the SMB segment this quarter",
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
                current_value=320,
                status=KeyResultStatus.ON_TRACK,
                owner_id=uuid4(),
                created_at=_now(),
                updated_at=_now(),
            )
        ],
        created_at=_now(),
        updated_at=_now(),
    )


def _coach_response_json(
    *,
    new_target: float | None = None,
    requires_confirmation: bool = False,
    kr_id: str = "00000000-0000-0000-0000-000000000000",
) -> str:
    return json.dumps(
        {
            "updates": [
                {
                    "key_result_id": kr_id,
                    "new_progress_value": 320,
                    "new_target_value": new_target,
                    "new_status": "on_track",
                    "confidence": "medium",
                    "blockers": None,
                    "narrative": "Up to 320 this week, on pace.",
                    "requires_confirmation": requires_confirmation,
                }
            ],
            "coaching_message": "Nice progress. What's the biggest unknown going into next week?",
            "follow_up_questions": ["What dependency could surprise you?"],
        }
    )


@pytest.mark.unit
async def test_coach_returns_response() -> None:
    objective = _objective()
    kr_id = str(objective.key_results[0].id)
    model = FakeChatModel(responses=[_coach_response_json(kr_id=kr_id)])

    result = await run_checkin(
        objective=objective,
        user_message="We're at 320 weekly active accounts this week, on track.",
        model=model,
    )
    assert isinstance(result, CoachResponse)
    assert len(result.updates) == 1
    assert result.updates[0].new_progress_value == 320


@pytest.mark.unit
async def test_coach_rejects_empty_message() -> None:
    model = FakeChatModel(responses=[])
    with pytest.raises(CoachError, match="must not be empty"):
        await run_checkin(
            objective=_objective(),
            user_message="",
            model=model,
        )


@pytest.mark.unit
async def test_coach_forces_confirmation_on_target_change() -> None:
    """Even if LLM forgets requires_confirmation, target changes always require it."""
    objective = _objective()
    kr_id = str(objective.key_results[0].id)
    payload = _coach_response_json(new_target=600, requires_confirmation=False, kr_id=kr_id)
    model = FakeChatModel(responses=[payload])

    result = await run_checkin(
        objective=objective,
        user_message="Let's lower the target to 600 — we don't have the SDR coverage.",
        model=model,
    )
    assert result.updates[0].requires_confirmation is True
    assert result.updates[0].new_target_value == 600


@pytest.mark.unit
async def test_coach_keeps_confirmation_off_for_simple_progress() -> None:
    objective = _objective()
    kr_id = str(objective.key_results[0].id)
    model = FakeChatModel(
        responses=[_coach_response_json(new_target=None, requires_confirmation=False, kr_id=kr_id)]
    )

    result = await run_checkin(
        objective=objective,
        user_message="We hit 320 this week.",
        model=model,
    )
    assert result.updates[0].requires_confirmation is False


@pytest.mark.unit
async def test_coach_rejects_invalid_json() -> None:
    model = FakeChatModel(responses=["not a json object"])
    with pytest.raises(CoachError):
        await run_checkin(
            objective=_objective(),
            user_message="any message",
            model=model,
        )
