"""LangGraph state machine — assembles the agent graph.

The graph runs ``drafter ↔ critic`` until the proposal passes the Critic, then
runs ``aligner`` for vertical and horizontal alignment checks, then either ends
successfully (verdict ``aligned``) or pauses at the ``human`` node (verdicts
``needs_review`` / ``blocked``).

Coach, Reflector, and Risk Sentinel are not part of this graph — they run on
their own triggers (cadence, quarter close, scheduled). They share the same
``OKRState`` and agent contracts but execute through their own entry points.

When a ``checkpointer`` is provided, the ``human`` node calls LangGraph's
``interrupt()`` primitive instead of ending the run. The graph pauses and the
caller resumes with a ``Command(resume=...)`` carrying the human's decision.
This is the modern LangGraph HITL pattern and avoids the END-then-resume
routing problem of the older approach.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from langgraph.graph import START, StateGraph
from langgraph.types import interrupt

from cascade.agents.aligner import check_alignment
from cascade.agents.contracts import DraftIteration
from cascade.agents.critic import critique_proposal
from cascade.agents.drafter import draft_objective
from cascade.orchestrator.state import OKRState
from cascade.orchestrator.supervisor import make_human_escalation, supervisor

if TYPE_CHECKING:
    from langchain_core.language_models import BaseChatModel
    from langgraph.checkpoint.base import BaseCheckpointSaver
    from langgraph.graph.state import CompiledStateGraph


def build_graph(
    *,
    model: BaseChatModel,
    checkpointer: BaseCheckpointSaver | None = None,
) -> CompiledStateGraph:
    """Construct and compile the agent graph.

    Args:
        model: The chat model the agents use. Injected so tests can substitute
            :class:`cascade.agents.llm.FakeChatModel` and so production can wire
            in retry and fallback behaviour.
        checkpointer: Optional state persister. Required for HITL resumption —
            the ``human`` node calls ``interrupt()`` and the graph pauses with
            state durable across processes. Pass an :class:`AsyncSqliteSaver`
            for single-process deployments and a ``PostgresSaver`` for
            multi-replica.

    Returns:
        A compiled LangGraph ready to invoke. Callers ``ainvoke`` with an initial
        :class:`OKRState`. With a checkpointer, also pass a config like
        ``{"configurable": {"thread_id": "<some-id>"}}``.
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
        """Pause for human input.

        The :func:`interrupt` call surfaces the escalation reason and current
        iteration history to the caller. The graph pauses; calling
        ``ainvoke(Command(resume=decision_payload), config=...)`` resumes
        execution with ``decision_payload`` returned from this call.

        When no checkpointer is configured, ``interrupt`` raises immediately —
        we fall back to the previous behaviour of recording the escalation in
        ``awaiting_human`` and ending the run.
        """
        escalation = make_human_escalation(state)

        if checkpointer is None:
            # No checkpointer — record the escalation marker and end. The caller
            # has to handle resumption manually. This preserves backwards
            # compatibility for tests that don't set up a checkpointer.
            return {"awaiting_human": escalation}

        # interrupt() raises GraphInterrupt internally; on resume it returns
        # whatever payload the caller passed via Command(resume=...).
        resume_payload = interrupt(
            {
                "reason": escalation.reason,
                "iteration_count": state.iteration_count,
                "proposal": state.proposal.model_dump() if state.proposal else None,
                "alignment": state.alignment.model_dump() if state.alignment else None,
            }
        )

        # Convert the resume payload into the state diff that re-routes the
        # supervisor. The caller is expected to send a dict like
        # {"decision": "commit"|"revise"|"abandon", "notes": "..."}.
        from cascade.orchestrator.resumption import (
            apply_resume_payload,
        )

        return apply_resume_payload(state=state, payload=resume_payload)

    graph: StateGraph = StateGraph(OKRState)
    graph.add_node("drafter", drafter_node)
    graph.add_node("critic", critic_node)
    graph.add_node("aligner", aligner_node)
    graph.add_node("human", human_node)

    graph.add_conditional_edges(START, supervisor)
    graph.add_conditional_edges("drafter", supervisor)
    graph.add_conditional_edges("critic", supervisor)
    graph.add_conditional_edges("aligner", supervisor)
    # After the human node returns (post-resume), the supervisor re-routes
    # based on the updated state — Drafter for revise, END via aligned
    # alignment for commit.
    graph.add_conditional_edges("human", supervisor)

    return graph.compile(checkpointer=checkpointer)


__all__ = ["build_graph"]
