"""Tests for :func:`apply_resume_payload`.

These cover the pure logic that translates a resume payload into a state
diff. End-to-end integration with the checkpointer lives in
``tests/integration/test_resumption.py``.
"""

from __future__ import annotations

from uuid import uuid4

import pytest

from cascade.agents.contracts import (
    AlignmentConflict,
    AlignmentResult,
    CritiqueResult,
    DimensionScore,
    HumanInterrupt,
    ProposedKeyResult,
    ProposedObjective,
)
from cascade.domain.enums import MetricType
from cascade.orchestrator.resumption import (
    ResumptionError,
    apply_resume_payload,
)
from cascade.orchestrator.state import OKRState


def _proposal() -> ProposedObjective:
    return ProposedObjective(
        title="Reach product-market fit in the SMB segment this quarter",
        key_results=[
            ProposedKeyResult(
                description="Lift weekly active accounts from 200 to 800",
                metric_type=MetricType.NUMBER,
                baseline_value=200,
                target_value=800,
            )
        ],
    )


def _critique(verdict: str = "pass") -> CritiqueResult:
    return CritiqueResult(
        specificity=DimensionScore(score=0.9, reasoning="r"),
        measurability=DimensionScore(score=0.9, reasoning="r"),
        ambition=DimensionScore(score=0.85, reasoning="r"),
        structure=DimensionScore(score=0.9, reasoning="r"),
        vague_phrases=[],
        verdict=verdict,  # type: ignore[arg-type]
        suggestions=[],
    )


def _alignment_blocked() -> AlignmentResult:
    return AlignmentResult(
        vertical_score=0.85,
        vertical_reasoning="ok",
        conflicts=[
            AlignmentConflict(
                peer_okr_id=str(uuid4()),
                peer_title="Conflicting peer",
                conflict_type="resource",
                description="Both OKRs need the same engineering capacity",
                severity="blocking",
            )
        ],
        verdict="blocked",
        suggestions=[],
    )


def _saved_state(
    *,
    proposal: ProposedObjective | None = None,
    alignment: AlignmentResult | None = None,
    critique: CritiqueResult | None = None,
) -> OKRState:
    return OKRState(
        intent="some intent",
        proposal=proposal or _proposal(),
        critique=critique or _critique("pass"),
        alignment=alignment,
        awaiting_human=HumanInterrupt(reason="alignment_conflict", payload={}),
    )


@pytest.mark.unit
def test_commit_with_existing_alignment_forces_aligned_verdict() -> None:
    state = _saved_state(alignment=_alignment_blocked())
    diff = apply_resume_payload(state=state, payload={"decision": "commit", "notes": "approved"})
    new_alignment = diff["alignment"]
    assert isinstance(new_alignment, AlignmentResult)
    assert new_alignment.verdict == "aligned"
    # Blocking conflicts demoted to info to preserve audit trail
    assert all(c.severity == "info" for c in new_alignment.conflicts)
    assert diff["awaiting_human"] is None


@pytest.mark.unit
def test_commit_without_prior_alignment_synthesises_one() -> None:
    """Commit on a critique=reject path (no alignment computed) synthesises aligned."""
    state = _saved_state(alignment=None)
    diff = apply_resume_payload(state=state, payload={"decision": "commit", "notes": "overriding"})
    new_alignment = diff["alignment"]
    assert isinstance(new_alignment, AlignmentResult)
    assert new_alignment.verdict == "aligned"
    assert "overriding" in new_alignment.vertical_reasoning


@pytest.mark.unit
def test_commit_without_proposal_raises() -> None:
    state = OKRState(
        intent="x",
        awaiting_human=HumanInterrupt(reason="iteration_cap_reached", payload={}),
    )
    with pytest.raises(ResumptionError, match="no proposal"):
        apply_resume_payload(state=state, payload={"decision": "commit"})


@pytest.mark.unit
def test_revise_clears_proposal_critique_and_alignment() -> None:
    state = _saved_state(alignment=_alignment_blocked())
    diff = apply_resume_payload(state=state, payload={"decision": "revise"})
    assert diff["proposal"] is None
    assert diff["critique"] is None
    assert diff["alignment"] is None
    assert diff["awaiting_human"] is None


@pytest.mark.unit
def test_abandon_synthesises_blocked_audit_marker() -> None:
    state = _saved_state()
    diff = apply_resume_payload(
        state=state,
        payload={"decision": "abandon", "notes": "No longer relevant for Q2"},
    )
    new_alignment = diff["alignment"]
    assert isinstance(new_alignment, AlignmentResult)
    assert new_alignment.verdict == "blocked"
    assert "No longer relevant for Q2" in new_alignment.conflicts[0].description


@pytest.mark.unit
def test_abandon_sets_awaiting_human_with_abandoned_reason() -> None:
    """Abandon must set ``awaiting_human`` to a HumanInterrupt with reason='abandoned'.

    Two reasons:
    1. The supervisor's first routing rule is "if awaiting_human is set,
       return END". Without this marker the run wouldn't terminate — it
       would fall through to "alignment.blocked → route to human", calling
       interrupt() again and re-pausing.
    2. The wire surface can render "abandoned" as the reason, distinguishing
       this terminal state from a regular alignment-blocked pause.
    """
    state = _saved_state()
    diff = apply_resume_payload(
        state=state,
        payload={"decision": "abandon", "notes": "no longer relevant"},
    )
    interrupt_marker = diff["awaiting_human"]
    assert interrupt_marker is not None
    assert interrupt_marker.reason == "abandoned"  # type: ignore[union-attr]
    # Notes are preserved on the marker payload for the audit trail.
    assert "no longer relevant" in str(interrupt_marker.payload)  # type: ignore[union-attr]


@pytest.mark.unit
def test_unknown_decision_raises() -> None:
    state = _saved_state()
    with pytest.raises(ResumptionError, match="unknown decision"):
        apply_resume_payload(state=state, payload={"decision": "bogus"})


@pytest.mark.unit
def test_payload_must_be_dict() -> None:
    state = _saved_state()
    with pytest.raises(ResumptionError, match="must be a dict"):
        apply_resume_payload(state=state, payload="commit")


@pytest.mark.unit
def test_commit_preserves_existing_alignment_reasoning() -> None:
    state = _saved_state(alignment=_alignment_blocked())
    diff = apply_resume_payload(state=state, payload={"decision": "commit"})
    new_alignment = diff["alignment"]
    assert isinstance(new_alignment, AlignmentResult)
    # The original reasoning stays — only the verdict and conflict severities
    # were rewritten.
    assert new_alignment.vertical_reasoning == "ok"
    assert new_alignment.vertical_score == 0.85
