"""Supervisor — the deterministic router for the agent graph.

The Supervisor is intentionally not an agent. It is a pure function that reads the
current state and returns the next node name (or ``END``). Keeping it deterministic
gives us:

- Predictable test surface area (no LLM variance to mock)
- Cheaper traces (the routing decision is one log line, not an LLM call)
- A clean place to enforce hard limits (iteration cap, HITL escalation)
"""

from __future__ import annotations

from typing import Literal

from langgraph.graph import END

from cascade.agents.contracts import HumanInterrupt
from cascade.orchestrator.state import OKRState

# Cap on Drafter↔Critic iterations before we stop the model and escalate to a human.
# Three iterations is the empirical sweet spot — most flaws the Critic catches are
# fixed in one revision; problems still present after three are usually structural.
ITERATION_CAP = 3

NodeName = Literal["drafter", "critic", "aligner", "human", "__end__"]


def supervisor(state: OKRState) -> NodeName:
    """Return the name of the next node to execute, or ``END`` to stop.

    Routing rules, in order:

    1. If the graph is awaiting human input → end the run; the caller resumes after
       the human responds.
    2. If we have no proposal yet → ``drafter``.
    3. If we have a proposal but no critique → ``critic``.
    4. If the critique verdict is ``reject`` → escalate to human.
    5. If the critique verdict is ``needs_revision`` and we're under cap → ``drafter``.
    6. If the critique verdict is ``needs_revision`` and at the cap → escalate to human.
    7. If the critique verdict is ``pass`` and no alignment yet → ``aligner``.
    8. If alignment verdict is ``blocked`` → escalate to human.
    9. If alignment verdict is ``needs_review`` → escalate to human.
    10. If alignment verdict is ``aligned`` → end successfully.
    """
    if state.awaiting_human is not None:
        return END  # type: ignore[return-value]

    if state.proposal is None:
        return "drafter"

    if state.critique is None:
        return "critic"

    if state.critique.verdict == "reject":
        return "human"

    if state.critique.verdict == "needs_revision":
        if state.iteration_count >= ITERATION_CAP:
            return "human"
        return "drafter"

    # Critique passed — move to alignment if we haven't already
    if state.alignment is None:
        return "aligner"

    if state.alignment.verdict == "blocked":
        return "human"

    if state.alignment.verdict == "needs_review":
        return "human"

    # alignment.verdict == "aligned"
    return END  # type: ignore[return-value]


def make_human_escalation(state: OKRState) -> HumanInterrupt:
    """Build the :class:`HumanInterrupt` payload for the human node.

    Encapsulates the difference between the various escalation reasons so the UI
    can render an appropriate prompt.
    """
    reason: str
    if (state.alignment is not None and state.alignment.verdict == "blocked") or (
        state.alignment is not None and state.alignment.verdict == "needs_review"
    ):
        reason = "alignment_conflict"
    elif state.critique is not None and state.critique.verdict == "reject":
        reason = "fundamental_reject"
    else:
        reason = "iteration_cap_reached"

    payload: dict[str, object] = {
        "iteration_count": state.iteration_count,
        "iterations": [it.model_dump() for it in state.iterations],
    }
    if state.alignment is not None:
        payload["alignment"] = state.alignment.model_dump()
    return HumanInterrupt(reason=reason, payload=payload)  # type: ignore[arg-type]
