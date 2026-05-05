"""Tests for the supervisor routing function."""

from __future__ import annotations

import pytest
from langgraph.graph import END

from cascade.agents.contracts import (
    CritiqueResult,
    DimensionScore,
    DraftIteration,
    HumanInterrupt,
    ProposedKeyResult,
    ProposedObjective,
)
from cascade.domain.enums import MetricType
from cascade.orchestrator.state import OKRState
from cascade.orchestrator.supervisor import (
    ITERATION_CAP,
    make_human_escalation,
    supervisor,
)


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


def _critique(verdict: str = "pass", min_score: float = 0.85) -> CritiqueResult:
    return CritiqueResult(
        specificity=DimensionScore(score=min_score, reasoning="r"),
        measurability=DimensionScore(score=0.9, reasoning="r"),
        ambition=DimensionScore(score=0.9, reasoning="r"),
        structure=DimensionScore(score=0.9, reasoning="r"),
        vague_phrases=[],
        verdict=verdict,  # type: ignore[arg-type]
        suggestions=[],
    )


@pytest.mark.unit
def test_supervisor_routes_to_drafter_when_no_proposal() -> None:
    state = OKRState(intent="Reach product-market fit")
    assert supervisor(state) == "drafter"


@pytest.mark.unit
def test_supervisor_routes_to_critic_when_proposal_present() -> None:
    state = OKRState(intent="x", proposal=_proposal())
    assert supervisor(state) == "critic"


@pytest.mark.unit
def test_supervisor_ends_on_pass() -> None:
    state = OKRState(intent="x", proposal=_proposal(), critique=_critique("pass"))
    assert supervisor(state) == END


@pytest.mark.unit
def test_supervisor_escalates_on_reject() -> None:
    state = OKRState(intent="x", proposal=_proposal(), critique=_critique("reject"))
    assert supervisor(state) == "human"


@pytest.mark.unit
def test_supervisor_loops_on_needs_revision() -> None:
    iterations = [
        DraftIteration(
            proposal=_proposal(),
            critique=_critique("needs_revision", 0.5),
            iteration=1,
        )
    ]
    state = OKRState(
        intent="x",
        proposal=_proposal(),
        critique=_critique("needs_revision", 0.5),
        iterations=iterations,
    )
    assert supervisor(state) == "drafter"


@pytest.mark.unit
def test_supervisor_escalates_at_iteration_cap() -> None:
    iterations = [
        DraftIteration(
            proposal=_proposal(),
            critique=_critique("needs_revision", 0.5),
            iteration=i,
        )
        for i in range(1, ITERATION_CAP + 1)
    ]
    state = OKRState(
        intent="x",
        proposal=_proposal(),
        critique=_critique("needs_revision", 0.5),
        iterations=iterations,
    )
    assert supervisor(state) == "human"


@pytest.mark.unit
def test_supervisor_ends_when_awaiting_human() -> None:
    state = OKRState(
        intent="x",
        proposal=_proposal(),
        critique=_critique("reject"),
        awaiting_human=HumanInterrupt(reason="fundamental_reject"),
    )
    assert supervisor(state) == END


@pytest.mark.unit
def test_human_escalation_reflects_reject_verdict() -> None:
    state = OKRState(
        intent="x",
        proposal=_proposal(),
        critique=_critique("reject", 0.3),
        iterations=[
            DraftIteration(
                proposal=_proposal(),
                critique=_critique("reject", 0.3),
                iteration=1,
            )
        ],
    )
    interrupt = make_human_escalation(state)
    assert interrupt.reason == "fundamental_reject"
    assert interrupt.payload["iteration_count"] == 1


@pytest.mark.unit
def test_human_escalation_reflects_iteration_cap() -> None:
    iterations = [
        DraftIteration(
            proposal=_proposal(),
            critique=_critique("needs_revision", 0.5),
            iteration=i,
        )
        for i in range(1, ITERATION_CAP + 1)
    ]
    state = OKRState(
        intent="x",
        proposal=_proposal(),
        critique=_critique("needs_revision", 0.5),
        iterations=iterations,
    )
    interrupt = make_human_escalation(state)
    assert interrupt.reason == "iteration_cap_reached"
    assert interrupt.payload["iteration_count"] == ITERATION_CAP
