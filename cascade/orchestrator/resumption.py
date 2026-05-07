"""Human-in-the-loop resumption.

When the agent graph reaches the ``human`` node with a checkpointer attached,
it calls LangGraph's :func:`interrupt` primitive. Execution pauses; the caller
sees a ``GraphInterrupt`` raised on the original ``ainvoke`` call (or, for
recent LangGraph versions, the run returns with an ``__interrupt__`` field in
the state).

To resume, the caller invokes the graph again with a
``Command(resume=payload)`` carrying the human's decision. The payload is
returned from the ``interrupt()`` call inside the human node, and
:func:`apply_resume_payload` converts it into the state diff that re-routes
the supervisor.

Three decisions are supported:

- **commit** — accept the latest proposal as-is. Alignment is forced to
  ``aligned`` (the human is the final authority on alignment); the graph
  reaches the success path.
- **revise** — reject the latest proposal and request another revision. The
  graph clears proposal/critique/alignment and the supervisor routes back to
  the Drafter.
- **abandon** — cancel the run. Alignment is forced to ``blocked`` with an
  audit conflict capturing the abandonment.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Literal

from langgraph.types import Command

from cascade.agents.contracts import (
    AlignmentConflict,
    AlignmentResult,
)
from cascade.orchestrator.state import OKRState

if TYPE_CHECKING:
    from langgraph.graph.state import CompiledStateGraph

HumanDecision = Literal["commit", "revise", "abandon"]


class ResumptionError(Exception):
    """Raised when a resume payload cannot be applied to the saved state."""


def apply_resume_payload(
    *,
    state: OKRState,
    payload: Any,
) -> dict[str, object]:
    """Translate a resume payload into a state diff.

    Called inside the ``human`` node when it returns from ``interrupt()``.
    The payload is whatever the caller passed via ``Command(resume=...)`` —
    we expect a dict like::

        {"decision": "commit", "notes": "approved"}

    Args:
        state: The current :class:`OKRState` at the human node.
        payload: The dict the caller resumed with.

    Returns:
        A partial state dict that the human node returns to the framework.
        The supervisor is then re-asked, routing the graph based on the
        updated state.

    Raises:
        ResumptionError: If the payload is malformed or the decision is
        invalid.
    """
    if not isinstance(payload, dict):
        raise ResumptionError(f"resume payload must be a dict, got {type(payload).__name__}")
    decision = payload.get("decision")
    if decision not in ("commit", "revise", "abandon"):
        raise ResumptionError(f"unknown decision in resume payload: {decision!r}")
    notes = payload.get("notes")

    if decision == "commit":
        return _commit_diff(state, notes)
    if decision == "revise":
        return _revise_diff(state, notes)
    return _abandon_diff(state, notes)


def _commit_diff(state: OKRState, notes: str | None) -> dict[str, object]:
    """Resume with a synthesised aligned alignment so the graph completes.

    The human is the final authority on alignment. If they say to commit, the
    graph treats that as an aligned verdict; the supervisor reaches END via
    the normal routing.
    """
    if state.proposal is None:
        raise ResumptionError(
            "Cannot commit — saved state has no proposal. "
            "The Drafter never produced one in this run."
        )

    if state.alignment is not None:
        # Preserve the Aligner's analysis but force the verdict and demote
        # any blocking conflicts to info — they happened, but the human
        # accepted the proposal anyway.
        aligned = state.alignment.model_copy(
            update={
                "verdict": "aligned",
                "conflicts": _demote_blocking_conflicts(state),
            }
        )
    else:
        # No alignment was computed (e.g. critique=reject path); synthesise.
        aligned = AlignmentResult(
            vertical_score=1.0,
            vertical_reasoning=(
                "Human reviewer accepted proposal directly" + (f" — note: {notes}" if notes else "")
            ),
            conflicts=[],
            verdict="aligned",
            suggestions=[],
        )

    return {
        "alignment": aligned,
        "awaiting_human": None,
    }


def _revise_diff(state: OKRState, notes: str | None) -> dict[str, object]:
    """Resume by clearing the proposal and going back to the Drafter.

    Iteration history is preserved (it uses the ``_append`` reducer), so the
    Drafter still sees what was tried in this run.
    """
    return {
        "proposal": None,
        "critique": None,
        "alignment": None,
        "awaiting_human": None,
    }


def _abandon_diff(state: OKRState, notes: str | None) -> dict[str, object]:
    """Resume into a terminal abandoned state.

    Alignment is forced to ``blocked`` with an audit conflict capturing the
    abandonment so the trail records what the human did and why.

    ``awaiting_human`` is set to a fresh ``HumanInterrupt(reason="abandoned")``.
    This serves two purposes:

    1. The supervisor's first routing rule is "if awaiting_human is set,
       return END". Without this marker, execution would fall through to
       "alignment.verdict == blocked → route to human", calling interrupt()
       again and re-pausing the run. (This was a latent v0.8.0 bug. The
       human node on the first invocation never wrote ``awaiting_human``
       because it used the ``interrupt()`` primitive instead, so the field
       defaulted to ``None`` post-resume — clearing it had no effect, and
       leaving it untouched also had no effect.)
    2. The wire surface (HitlPauseInfo / HitlCompleteInfo) can render
       "abandoned" as the reason, distinguishing this terminal state from
       a regular alignment-blocked pause.
    """
    from cascade.agents.contracts import HumanInterrupt

    abandon_marker = AlignmentResult(
        vertical_score=0.0,
        vertical_reasoning=(
            "Human reviewer abandoned the run" + (f" — note: {notes}" if notes else "")
        ),
        conflicts=[
            AlignmentConflict(
                peer_okr_id=None,
                peer_title="(abandoned by human reviewer)",
                conflict_type="scope",
                description=(
                    "Human reviewer chose to abandon this drafting run rather "
                    "than commit or revise." + (f" Note: {notes}" if notes else "")
                ),
                severity="blocking",
            )
        ],
        verdict="blocked",
        suggestions=[],
    )
    return {
        "alignment": abandon_marker,
        "awaiting_human": HumanInterrupt(
            reason="abandoned",
            payload={"notes": notes} if notes else {},
        ),
    }


def _demote_blocking_conflicts(state: OKRState) -> list[AlignmentConflict]:
    """Demote blocking conflicts to info on a human commit override."""
    if state.alignment is None:
        return []
    return [
        c.model_copy(update={"severity": "info"}) if c.severity == "blocking" else c
        for c in state.alignment.conflicts
    ]


async def resume(
    *,
    graph: CompiledStateGraph,
    thread_id: str,
    decision: HumanDecision,
    notes: str | None = None,
) -> dict[str, object]:
    """Resume a paused graph run after a human decision.

    Convenience wrapper that builds the resume payload, sends a
    :class:`Command` carrying it, and waits for the graph to settle.

    Args:
        graph: The compiled graph (must have a checkpointer).
        thread_id: The thread id used in the original run's config.
        decision: The human's choice.
        notes: Optional human-supplied notes for the audit trail.

    Returns:
        The final graph state after the resumed run completes.
    """
    config = {"configurable": {"thread_id": thread_id}}
    payload = {"decision": decision, "notes": notes}
    return await graph.ainvoke(Command(resume=payload), config=config)


__all__ = [
    "HumanDecision",
    "ResumptionError",
    "apply_resume_payload",
    "resume",
]
