"""LangGraph state machine — assembles the agent graph.

The graph runs ``drafter ↔ critic`` until the proposal passes the Critic, then
runs ``aligner`` for vertical and horizontal alignment checks, then either ends
successfully (verdict ``aligned``) or escalates to a human (verdicts
``needs_review`` / ``blocked``).

Coach, Reflector, and Risk Sentinel are not part of this graph — they run on
their own triggers (cadence, quarter close, scheduled). They share the same
``OKRState`` and agent contracts but execute through their own entry points.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from langgraph.graph import END, START, StateGraph

from cascade.agents.aligner import check_alignment
from cascade.agents.contracts import DraftIteration
from cascade.agents.critic import critique_proposal
from cascade.agents.drafter import draft_objective
from cascade.orchestrator.state import OKRState
from cascade.orchestrator.supervisor import make_human_escalation, supervisor

if TYPE_CHECKING:
    from langchain_core.language_models import BaseChatModel
    from langgraph.graph.state import CompiledStateGraph


def build_graph(*, model: BaseChatModel) -> CompiledStateGraph:
    """Construct and compile the agent graph.

    Args:
        model: The chat model the agents use. Injected so tests can substitute
            :class:`cascade.agents.llm.FakeChatModel` and so production can wire
            in retry and fallback behaviour.

    Returns:
        A compiled LangGraph ready to invoke. Callers ``ainvoke`` with an initial
        :class:`OKRState`.
    """

    async def drafter_node(state: OKRState) -> dict[str, object]:
        proposal = await draft_objective(
            intent=state.intent,
            model=model,
            parent_objective=state.parent_objective,
            previous_attempts=state.iterations,
        )
        return {"proposal": proposal, "critique": None, "alignment": None}

    async def critic_node(state: OKRState) -> dict[str, object]:
        if state.proposal is None:
            raise RuntimeError("critic_node called before a proposal was drafted")
        critique = await critique_proposal(proposal=state.proposal, model=model)
        new_iteration = DraftIteration(
            proposal=state.proposal,
            critique=critique,
            iteration=state.iteration_count + 1,
        )
        return {"critique": critique, "iterations": [new_iteration]}

    async def aligner_node(state: OKRState) -> dict[str, object]:
        if state.proposal is None:
            raise RuntimeError("aligner_node called before a proposal was drafted")
        alignment = await check_alignment(
            proposal=state.proposal,
            parent_objective=state.parent_objective,
            peer_objectives=state.peer_objectives,
            model=model,
        )
        return {"alignment": alignment}

    async def human_node(state: OKRState) -> dict[str, object]:
        return {"awaiting_human": make_human_escalation(state)}

    graph: StateGraph = StateGraph(OKRState)
    graph.add_node("drafter", drafter_node)
    graph.add_node("critic", critic_node)
    graph.add_node("aligner", aligner_node)
    graph.add_node("human", human_node)

    # Initial entry: the Supervisor decides where to begin based on the seeded state.
    graph.add_conditional_edges(START, supervisor)
    graph.add_conditional_edges("drafter", supervisor)
    graph.add_conditional_edges("critic", supervisor)
    graph.add_conditional_edges("aligner", supervisor)
    # The human node is terminal for this phase — the caller resumes after input.
    graph.add_edge("human", END)

    return graph.compile()


__all__ = ["build_graph"]
