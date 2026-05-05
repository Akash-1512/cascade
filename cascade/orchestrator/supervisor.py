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

NodeName = Literal["drafter", "critic", "human", "__end__"]


def supervisor(state: OKRState) -> NodeName:
    """Return the name of the next node to execute, or ``END`` to stop.

    Routing rules, in order:

    1. If the graph is awaiting human input → end the run; the caller resumes after
       the human responds.
    2. If we have no proposal yet → ``drafter``.
    3. If we have a proposal but no critique → ``critic``.
    4. If the critique verdict is ``pass`` → end successfully.
    5. If the critique verdict is ``reject`` → escalate to human.
    6. If the iteration cap has been reached → escalate to human.
    7. Otherwise the verdict is ``needs_revision`` → loop back to ``drafter``.
    """
    if state.awaiting_human is not None:
        return END  # type: ignore[return-value]

    if state.proposal is None:
        return "drafter"

    if state.critique is None:
        return "critic"

    if state.critique.verdict == "pass":
        return END  # type: ignore[return-value]

    if state.critique.verdict == "reject":
        return "human"

    if state.iteration_count >= ITERATION_CAP:
        return "human"

    return "drafter"


def make_human_escalation(state: OKRState) -> HumanInterrupt:
    """Build the :class:`HumanInterrupt` payload for the human node.

    Encapsulates the difference between "the model gave up" and "we ran out of
    iterations" so the UI can render an appropriate prompt.
    """
    if state.critique is not None and state.critique.verdict == "reject":
        reason = "fundamental_reject"
    else:
        reason = "iteration_cap_reached"

    payload: dict[str, object] = {
        "iteration_count": state.iteration_count,
        "iterations": [it.model_dump() for it in state.iterations],
    }
    return HumanInterrupt(reason=reason, payload=payload)  # type: ignore[arg-type]
