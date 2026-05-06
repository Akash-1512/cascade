"""Tests for the Aligner agent."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from uuid import uuid4

import pytest

from cascade.agents.aligner import (
    VERTICAL_BLOCK_THRESHOLD,
    VERTICAL_PASS_THRESHOLD,
    AlignerError,
    check_alignment,
)
from cascade.agents.contracts import (
    AlignmentResult,
    ProposedKeyResult,
    ProposedObjective,
)
from cascade.agents.llm import FakeChatModel
from cascade.domain.enums import KeyResultStatus, MetricType, ObjectiveStatus
from cascade.domain.okr import KeyResult, Objective, Quarter


def _now() -> datetime:
    return datetime.now(tz=UTC)


def _proposal() -> ProposedObjective:
    return ProposedObjective(
        title="Reach product-market fit in the SMB segment",
        key_results=[
            ProposedKeyResult(
                description="Lift weekly active accounts from 200 to 800",
                metric_type=MetricType.NUMBER,
                baseline_value=200,
                target_value=800,
            ),
        ],
    )


def _objective(title: str = "Parent OKR for company-wide growth") -> Objective:
    oid = uuid4()
    return Objective(
        id=oid,
        title=title,
        owner_id=uuid4(),
        team_id=uuid4(),
        quarter=Quarter(year=2026, quarter=2),
        status=ObjectiveStatus.ACTIVE,
        key_results=[
            KeyResult(
                objective_id=oid,
                description="A measurable parent KR for growth this quarter",
                metric_type=MetricType.NUMBER,
                baseline_value=0,
                target_value=1000,
                current_value=200,
                status=KeyResultStatus.ON_TRACK,
                owner_id=uuid4(),
                created_at=_now(),
                updated_at=_now(),
            )
        ],
        created_at=_now(),
        updated_at=_now(),
    )


def _alignment_json(
    *,
    vertical: float = 0.85,
    verdict: str = "aligned",
    conflicts: list[dict] | None = None,
) -> str:
    return json.dumps(
        {
            "vertical_score": vertical,
            "vertical_reasoning": "ok",
            "conflicts": conflicts or [],
            "verdict": verdict,
            "suggestions": [],
        }
    )


@pytest.mark.unit
async def test_aligner_returns_alignment_result() -> None:
    model = FakeChatModel(responses=[_alignment_json()])
    result = await check_alignment(
        proposal=_proposal(),
        parent_objective=_objective(),
        peer_objectives=[],
        model=model,
    )
    assert isinstance(result, AlignmentResult)
    assert result.verdict == "aligned"


@pytest.mark.unit
async def test_aligner_blocks_below_block_threshold() -> None:
    """Vertical score below 0.4 forces verdict to blocked even if LLM said aligned."""
    payload = _alignment_json(vertical=0.3, verdict="aligned")
    model = FakeChatModel(responses=[payload])
    result = await check_alignment(
        proposal=_proposal(),
        parent_objective=_objective(),
        peer_objectives=[],
        model=model,
    )
    assert result.verdict == "blocked"
    assert result.vertical_score < VERTICAL_BLOCK_THRESHOLD


@pytest.mark.unit
async def test_aligner_softens_to_review_in_borderline_band() -> None:
    payload = _alignment_json(vertical=0.5, verdict="aligned")
    model = FakeChatModel(responses=[payload])
    result = await check_alignment(
        proposal=_proposal(),
        parent_objective=_objective(),
        peer_objectives=[],
        model=model,
    )
    assert result.verdict == "needs_review"
    assert VERTICAL_BLOCK_THRESHOLD <= result.vertical_score < VERTICAL_PASS_THRESHOLD


@pytest.mark.unit
async def test_aligner_blocks_on_blocking_conflict() -> None:
    """Any blocking conflict forces verdict to blocked even with high vertical score."""
    payload = _alignment_json(
        vertical=0.95,
        verdict="aligned",
        conflicts=[
            {
                "peer_okr_id": str(uuid4()),
                "peer_title": "Conflicting peer OKR",
                "conflict_type": "resource",
                "description": "Both OKRs need the same engineering capacity",
                "severity": "blocking",
            }
        ],
    )
    model = FakeChatModel(responses=[payload])
    result = await check_alignment(
        proposal=_proposal(),
        parent_objective=_objective(),
        peer_objectives=[],
        model=model,
    )
    assert result.verdict == "blocked"


@pytest.mark.unit
async def test_aligner_softens_on_warning_conflict() -> None:
    payload = _alignment_json(
        vertical=0.9,
        verdict="aligned",
        conflicts=[
            {
                "peer_okr_id": None,
                "peer_title": "Sibling OKR",
                "conflict_type": "scope",
                "description": "Some scope overlap to discuss",
                "severity": "warning",
            }
        ],
    )
    model = FakeChatModel(responses=[payload])
    result = await check_alignment(
        proposal=_proposal(),
        parent_objective=_objective(),
        peer_objectives=[],
        model=model,
    )
    assert result.verdict == "needs_review"


@pytest.mark.unit
async def test_aligner_handles_no_parent() -> None:
    """When no parent is given the prompt asks for vertical=1.0; verdict aligned."""
    model = FakeChatModel(responses=[_alignment_json(vertical=1.0)])
    result = await check_alignment(
        proposal=_proposal(),
        parent_objective=None,
        peer_objectives=[],
        model=model,
    )
    assert result.verdict == "aligned"


@pytest.mark.unit
async def test_aligner_rejects_invalid_json() -> None:
    model = FakeChatModel(responses=["not json"])
    with pytest.raises(AlignerError):
        await check_alignment(
            proposal=_proposal(),
            parent_objective=None,
            peer_objectives=[],
            model=model,
        )
