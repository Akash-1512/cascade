"""Tests for the MCP adapter layer."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

import pytest

from cascade.agents.contracts import (
    AlignmentConflict,
    AlignmentResult,
    ProposedKeyResult,
    ProposedObjective,
    RiskAssessment,
    RiskFactor,
)
from cascade.domain.decision import Alternative, Decision, Evidence
from cascade.domain.enums import (
    DecisionEventType,
    KeyResultStatus,
    MetricType,
    ObjectiveStatus,
)
from cascade.domain.okr import KeyResult, Objective, Quarter
from cascade.mcp.adapters import (
    to_alignment_view,
    to_decision_view,
    to_drafted_objective,
    to_objective_summary,
    to_objective_view,
    to_risk_view,
)
from cascade.mcp.schemas import ObjectiveSummary, ObjectiveView


def _now() -> datetime:
    return datetime.now(tz=UTC)


def _objective() -> Objective:
    oid = uuid4()
    kr = KeyResult(
        objective_id=oid,
        description="Lift weekly active accounts from 200 to 800",
        metric_type=MetricType.NUMBER,
        baseline_value=200,
        target_value=800,
        current_value=500,
        unit="accounts",
        weight=1.5,
        status=KeyResultStatus.ON_TRACK,
        owner_id=uuid4(),
        created_at=_now(),
        updated_at=_now(),
    )
    return Objective(
        id=oid,
        title="Reach product-market fit in the SMB segment",
        description="Q2 focus on SMB conversion",
        owner_id=uuid4(),
        team_id=uuid4(),
        quarter=Quarter(year=2026, quarter=2),
        status=ObjectiveStatus.ACTIVE,
        key_results=[kr],
        created_at=_now(),
        updated_at=_now(),
    )


@pytest.mark.unit
def test_to_objective_view_renders_uuids_as_strings() -> None:
    okr = _objective()
    view = to_objective_view(okr)
    assert isinstance(view, ObjectiveView)
    assert view.id == str(okr.id)
    assert view.team_id == str(okr.team_id)
    assert view.owner_id == str(okr.owner_id)


@pytest.mark.unit
def test_to_objective_view_carries_score() -> None:
    okr = _objective()
    view = to_objective_view(okr)
    # Linear scoring: baseline=200, current=500, target=800 → 0.5
    assert view.score == pytest.approx(0.5)
    assert view.key_results[0].score == pytest.approx(0.5)


@pytest.mark.unit
def test_to_objective_view_renders_quarter_as_string() -> None:
    okr = _objective()
    view = to_objective_view(okr)
    assert view.quarter == "2026Q2"


@pytest.mark.unit
def test_to_objective_view_handles_missing_parent() -> None:
    okr = _objective()
    view = to_objective_view(okr)
    assert view.parent_objective_id is None


@pytest.mark.unit
def test_to_objective_summary_compact_shape() -> None:
    okr = _objective()
    summary = to_objective_summary(okr)
    assert isinstance(summary, ObjectiveSummary)
    assert summary.id == str(okr.id)
    assert summary.title == okr.title
    assert summary.quarter == "2026Q2"


@pytest.mark.unit
def test_to_decision_view_renders_alternatives_and_evidence() -> None:
    decision = Decision(
        event_type=DecisionEventType.KR_TARGET_CHANGE,
        objective_id=uuid4(),
        key_result_id=uuid4(),
        summary="Lowered enterprise win-rate target from 30% to 25%",
        alternatives=[
            Alternative(option="Hold target at 30%", reason_rejected="No SDR coverage"),
            Alternative(option="Drop the KR", reason_rejected="Removes the only signal"),
        ],
        chosen="Lowered to 25%",
        tradeoff="Accepts slower growth in Q2",
        evidence=[
            Evidence(
                source="Pipeline review Apr 14",
                claim="Coverage ratio dropped 4.0x to 2.6x",
                link="https://example.com/p1",
            )
        ],
        actor_id=uuid4(),
        created_at=_now(),
    )
    view = to_decision_view(decision)
    assert len(view.alternatives) == 2
    assert view.alternatives[0]["option"] == "Hold target at 30%"
    assert view.alternatives[0]["reason_rejected"] == "No SDR coverage"
    assert view.evidence[0]["link"] == "https://example.com/p1"
    assert view.tradeoff == "Accepts slower growth in Q2"


@pytest.mark.unit
def test_to_decision_view_evidence_link_normalised_to_empty_string() -> None:
    """When no link is provided we surface '' rather than null — keeps client parsing simple."""
    decision = Decision(
        event_type=DecisionEventType.OBJECTIVE_COMMIT,
        objective_id=uuid4(),
        summary="Committed initial draft after team review",
        chosen="Proceed",
        evidence=[Evidence(source="Standup notes", claim="Owner agreed verbally")],
        actor_id=uuid4(),
        created_at=_now(),
    )
    view = to_decision_view(decision)
    assert view.evidence[0]["link"] == ""


@pytest.mark.unit
def test_to_drafted_objective_preserves_metric_types() -> None:
    proposal = ProposedObjective(
        title="Reach product-market fit in the SMB segment",
        key_results=[
            ProposedKeyResult(
                description="Lift weekly active accounts",
                metric_type=MetricType.NUMBER,
                baseline_value=200,
                target_value=800,
            ),
            ProposedKeyResult(
                description="Improve conversion from 12% to 22%",
                metric_type=MetricType.PERCENTAGE,
                baseline_value=12,
                target_value=22,
            ),
        ],
    )
    view = to_drafted_objective(proposal)
    assert view.key_results[0].metric_type == "number"
    assert view.key_results[1].metric_type == "percentage"


@pytest.mark.unit
def test_to_risk_view_carries_factors_and_interventions() -> None:
    risk = RiskAssessment(
        okr_id=str(uuid4()),
        risk_score=0.65,
        velocity_assessment="slowing",
        factors=[
            RiskFactor(
                name="Velocity slowdown",
                severity="medium",
                explanation="Last two check-ins showed declining delta",
            )
        ],
        recommended_interventions=["Surface dependency to data team lead"],
        requires_intervention=True,
    )
    view = to_risk_view(risk)
    assert view.objective_id == risk.okr_id
    assert view.risk_score == pytest.approx(0.65)
    assert len(view.factors) == 1
    assert view.factors[0].severity == "medium"


@pytest.mark.unit
def test_to_alignment_view_carries_conflicts() -> None:
    objective_id = str(uuid4())
    alignment = AlignmentResult(
        vertical_score=0.55,
        vertical_reasoning="Tenuous link to parent",
        conflicts=[
            AlignmentConflict(
                peer_okr_id=str(uuid4()),
                peer_title="Conflicting peer OKR",
                conflict_type="resource",
                description="Both need the same engineering capacity",
                severity="warning",
            )
        ],
        verdict="needs_review",
        suggestions=["Discuss resource allocation in next staff meeting"],
    )
    view = to_alignment_view(alignment, objective_id=objective_id)
    assert view.objective_id == objective_id
    assert view.verdict == "needs_review"
    assert len(view.conflicts) == 1
    assert view.conflicts[0].conflict_type == "resource"
