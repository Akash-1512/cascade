"""LangGraph state machine — assembles the agent graph.

Phase 2 graph: ``drafter ↔ critic`` loop with HITL escalation. Aligner, Coach,
Reflector, and Risk Sentinel slot in here in subsequent phases without changing the
core orchestration code — they are added as additional nodes and the Supervisor's
routing rules grow accordingly.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from langgraph.graph import END, START, StateGraph

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
        model: The chat model the Drafter and Critic use. Injected so tests can
            substitute :class:`cascade.agents.llm.FakeChatModel` and so production
            can wire in retry and fallback behaviour.

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
        return {"proposal": proposal, "critique": None}

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

    async def human_node(state: OKRState) -> dict[str, object]:
        return {"awaiting_human": make_human_escalation(state)}

    graph: StateGraph = StateGraph(OKRState)
    graph.add_node("drafter", drafter_node)
    graph.add_node("critic", critic_node)
    graph.add_node("human", human_node)

    # Initial entry: the Supervisor decides where to begin based on the seeded state.
    graph.add_conditional_edges(START, supervisor)
    graph.add_conditional_edges("drafter", supervisor)
    graph.add_conditional_edges("critic", supervisor)
    # The human node is terminal for this phase — the caller resumes after input.
    graph.add_edge("human", END)

    return graph.compile()


__all__ = ["build_graph"]
