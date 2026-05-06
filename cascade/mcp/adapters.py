"""Adapters between :mod:`cascade.domain` and :mod:`cascade.mcp.schemas`.

Adapters live in their own module so the domain layer stays free of MCP-specific
concerns and the MCP layer stays free of import paths back into agents and
storage. A change to the wire format never propagates inward.
"""

from __future__ import annotations

from cascade.agents.contracts import (
    AlignmentResult,
    ProposedObjective,
    RiskAssessment,
)
from cascade.domain.decision import Decision
from cascade.domain.okr import KeyResult, Objective
from cascade.mcp.schemas import (
    AlignmentConflictView,
    AlignmentResultView,
    DecisionView,
    DraftedKeyResult,
    DraftedObjective,
    KeyResultView,
    ObjectiveSummary,
    ObjectiveView,
    RiskAssessmentView,
    RiskFactorView,
)


def to_objective_view(okr: Objective) -> ObjectiveView:
    """Convert a domain :class:`Objective` into the MCP wire view."""
    return ObjectiveView(
        id=str(okr.id),
        title=okr.title,
        description=okr.description,
        quarter=str(okr.quarter),
        status=okr.status.value,  # type: ignore[arg-type]
        team_id=str(okr.team_id),
        owner_id=str(okr.owner_id),
        parent_objective_id=str(okr.parent_objective_id) if okr.parent_objective_id else None,
        score=okr.score,
        key_results=[to_kr_view(kr) for kr in okr.key_results],
        created_at=okr.created_at,
        updated_at=okr.updated_at,
    )


def to_objective_summary(okr: Objective) -> ObjectiveSummary:
    """Compact list-view of an :class:`Objective`."""
    return ObjectiveSummary(
        id=str(okr.id),
        title=okr.title,
        quarter=str(okr.quarter),
        status=okr.status.value,  # type: ignore[arg-type]
        score=okr.score,
    )


def to_kr_view(kr: KeyResult) -> KeyResultView:
    """Convert a domain :class:`KeyResult` into the MCP wire view."""
    return KeyResultView(
        id=str(kr.id),
        description=kr.description,
        metric_type=kr.metric_type.value,  # type: ignore[arg-type]
        baseline_value=kr.baseline_value,
        target_value=kr.target_value,
        current_value=kr.current_value,
        unit=kr.unit,
        weight=kr.weight,
        status=kr.status.value,  # type: ignore[arg-type]
        score=kr.score,
    )


def to_decision_view(d: Decision) -> DecisionView:
    """Convert a :class:`Decision` into the MCP wire view."""
    return DecisionView(
        id=str(d.id),
        event_type=d.event_type.value,  # type: ignore[arg-type]
        objective_id=str(d.objective_id),
        key_result_id=str(d.key_result_id) if d.key_result_id else None,
        summary=d.summary,
        alternatives=[
            {"option": alt.option, "reason_rejected": alt.reason_rejected} for alt in d.alternatives
        ],
        chosen=d.chosen,
        tradeoff=d.tradeoff,
        evidence=[
            {
                "source": e.source,
                "claim": e.claim,
                "link": e.link or "",
            }
            for e in d.evidence
        ],
        actor_id=str(d.actor_id),
        created_at=d.created_at,
    )


def to_drafted_objective(proposal: ProposedObjective) -> DraftedObjective:
    """Convert a Drafter's :class:`ProposedObjective` into the MCP wire view."""
    return DraftedObjective(
        title=proposal.title,
        description=proposal.description,
        key_results=[
            DraftedKeyResult(
                description=kr.description,
                metric_type=kr.metric_type.value,  # type: ignore[arg-type]
                baseline_value=kr.baseline_value,
                target_value=kr.target_value,
                current_value=kr.current_value,
                unit=kr.unit,
                weight=kr.weight,
            )
            for kr in proposal.key_results
        ],
    )


def to_risk_view(risk: RiskAssessment) -> RiskAssessmentView:
    """Convert a :class:`RiskAssessment` to its MCP wire view."""
    return RiskAssessmentView(
        objective_id=risk.okr_id,
        risk_score=risk.risk_score,
        velocity_assessment=risk.velocity_assessment,
        factors=[
            RiskFactorView(
                name=f.name,
                severity=f.severity,
                explanation=f.explanation,
            )
            for f in risk.factors
        ],
        recommended_interventions=list(risk.recommended_interventions),
        requires_intervention=risk.requires_intervention,
    )


def to_alignment_view(alignment: AlignmentResult, *, objective_id: str) -> AlignmentResultView:
    """Convert an :class:`AlignmentResult` to its MCP wire view."""
    return AlignmentResultView(
        objective_id=objective_id,
        vertical_score=alignment.vertical_score,
        vertical_reasoning=alignment.vertical_reasoning,
        conflicts=[
            AlignmentConflictView(
                peer_okr_id=c.peer_okr_id,
                peer_title=c.peer_title,
                conflict_type=c.conflict_type,
                description=c.description,
                severity=c.severity,
            )
            for c in alignment.conflicts
        ],
        verdict=alignment.verdict,
        suggestions=list(alignment.suggestions),
    )
