"""End-to-end HITL resumption via LangGraph's :func:`interrupt` primitive.

Pattern:

1. Build the graph with an :class:`AsyncSqliteSaver` checkpointer.
2. ``ainvoke`` with initial state and a thread_id.
3. Graph runs until the human node calls ``interrupt()``; the run returns
   with an ``__interrupt__`` field (LangGraph 1.0+) or raises a
   ``GraphInterrupt`` (older versions).
4. The caller resumes with ``Command(resume={"decision": "...", "notes": "..."})``
   on the same thread_id; the human node returns from ``interrupt()`` with
   that payload, which is converted to a state diff via
   :func:`apply_resume_payload`.
5. The supervisor re-routes from the human node based on the updated state.
"""

from __future__ import annotations

import json

import pytest
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver

from cascade.agents.llm import FakeChatModel
from cascade.orchestrator.graph import build_graph
from cascade.orchestrator.resumption import resume
from cascade.orchestrator.state import OKRState


def _proposal_json() -> str:
    return json.dumps(
        {
            "title": "Reach product-market fit in the SMB segment",
            "description": None,
            "key_results": [
                {
                    "description": "Lift weekly active accounts from 200 to 800",
                    "metric_type": "number",
                    "baseline_value": 200,
                    "target_value": 800,
                    "current_value": 200,
                    "unit": "accounts",
                    "weight": 1.0,
                }
            ],
        }
    )


def _critique_json(verdict: str, score: float = 0.85) -> str:
    return json.dumps(
        {
            "specificity": {"score": score, "reasoning": "ok"},
            "measurability": {"score": score, "reasoning": "ok"},
            "ambition": {"score": score, "reasoning": "ok"},
            "structure": {"score": score, "reasoning": "ok"},
            "vague_phrases": [],
            "verdict": verdict,
            "suggestions": [] if verdict == "pass" else ["Sharpen the segment definition"],
        }
    )


def _alignment_json(verdict: str) -> str:
    conflicts = (
        []
        if verdict == "aligned"
        else [
            {
                "peer_okr_id": None,
                "peer_title": "Conflicting peer OKR",
                "conflict_type": "resource",
                "description": "Both OKRs need the same engineering capacity",
                "severity": "blocking",
            }
        ]
    )
    return json.dumps(
        {
            "vertical_score": 0.9,
            "vertical_reasoning": "Direct contribution to parent",
            "conflicts": conflicts,
            "verdict": verdict,
            "suggestions": [],
        }
    )


@pytest.mark.integration
async def test_graph_compiles_with_checkpointer() -> None:
    async with AsyncSqliteSaver.from_conn_string(":memory:") as saver:
        model = FakeChatModel(responses=[])
        graph = build_graph(model=model, checkpointer=saver)
        assert graph is not None


@pytest.mark.integration
async def test_run_pauses_at_human_node_with_interrupt() -> None:
    """The graph pauses at the human node — state has an ``__interrupt__`` marker."""
    async with AsyncSqliteSaver.from_conn_string(":memory:") as saver:
        model = FakeChatModel(
            responses=[
                _proposal_json(),
                _critique_json("pass"),
                _alignment_json("blocked"),
            ]
        )
        graph = build_graph(model=model, checkpointer=saver)
        config = {"configurable": {"thread_id": "test-pause-001"}}

        result = await graph.ainvoke(
            OKRState(intent="Reach PMF in SMB", trace_id="t1"), config=config
        )

        # LangGraph surfaces interrupts in the result via __interrupt__
        assert "__interrupt__" in result
        # State at the pause is fetchable from the checkpointer
        snapshot = await graph.aget_state(config)
        assert snapshot is not None
        # The human node is the next pending node — it called interrupt() and
        # is paused mid-execution
        assert "human" in snapshot.next


@pytest.mark.integration
async def test_resume_with_commit_decision_completes_run() -> None:
    """Human commits — run resumes and completes with aligned alignment."""
    async with AsyncSqliteSaver.from_conn_string(":memory:") as saver:
        model = FakeChatModel(
            responses=[
                _proposal_json(),
                _critique_json("pass"),
                _alignment_json("blocked"),
            ]
        )
        graph = build_graph(model=model, checkpointer=saver)
        config = {"configurable": {"thread_id": "test-resume-002"}}

        await graph.ainvoke(OKRState(intent="Reach PMF in SMB"), config=config)

        final = await resume(
            graph=graph,
            thread_id="test-resume-002",
            decision="commit",
            notes="Approved despite resource conflict",
        )

        assert final["alignment"].verdict == "aligned"
        # Conflicts demoted from blocking to info — preserves audit trail
        assert all(c.severity == "info" for c in final["alignment"].conflicts)
        assert final.get("awaiting_human") is None


@pytest.mark.integration
async def test_resume_with_revise_decision_returns_to_drafter() -> None:
    """Human asks for revision — graph clears proposal and re-runs Drafter."""
    async with AsyncSqliteSaver.from_conn_string(":memory:") as saver:
        model = FakeChatModel(
            responses=[
                # First pass: drafter, critic (pass), aligner (blocked) -> human
                _proposal_json(),
                _critique_json("pass"),
                _alignment_json("blocked"),
                # After revise: drafter, critic (pass), aligner (aligned)
                _proposal_json(),
                _critique_json("pass"),
                _alignment_json("aligned"),
            ]
        )
        graph = build_graph(model=model, checkpointer=saver)
        config = {"configurable": {"thread_id": "test-resume-003"}}

        await graph.ainvoke(OKRState(intent="Reach PMF in SMB"), config=config)

        final = await resume(
            graph=graph,
            thread_id="test-resume-003",
            decision="revise",
        )

        assert final["alignment"].verdict == "aligned"
        assert final.get("awaiting_human") is None
        # Iteration count grew across the two drafting passes
        assert len(final["iterations"]) >= 2


@pytest.mark.integration
async def test_resume_with_abandon_decision_terminates_with_audit_marker() -> None:
    """Human abandons — final state is blocked with an audit conflict and the
    run actually terminates (no ``__interrupt__`` in the result)."""
    async with AsyncSqliteSaver.from_conn_string(":memory:") as saver:
        model = FakeChatModel(
            responses=[
                _proposal_json(),
                _critique_json("pass"),
                _alignment_json("blocked"),
            ]
        )
        graph = build_graph(model=model, checkpointer=saver)
        config = {"configurable": {"thread_id": "test-resume-004"}}

        await graph.ainvoke(OKRState(intent="Reach PMF in SMB"), config=config)

        final = await resume(
            graph=graph,
            thread_id="test-resume-004",
            decision="abandon",
            notes="No longer relevant for Q2",
        )

        assert final["alignment"].verdict == "blocked"
        assert any(
            "No longer relevant for Q2" in c.description for c in final["alignment"].conflicts
        )
        # The run must actually terminate — no pause, no interrupt marker.
        # A buggy abandon (clearing awaiting_human) would route back to the
        # human node and re-pause; the supervisor's awaiting_human-is-set
        # rule is what makes abandon truly terminal.
        assert "__interrupt__" not in final, (
            "Abandon should terminate the run; got a pause marker in the result"
        )


@pytest.mark.integration
async def test_graph_without_checkpointer_falls_back_to_legacy_path() -> None:
    """No checkpointer — human node sets ``awaiting_human`` and ends.

    This preserves backwards compatibility for callers that don't need HITL
    resumption: they get the previous "ended at human node" behaviour.
    """
    model = FakeChatModel(
        responses=[
            _proposal_json(),
            _critique_json("pass"),
            _alignment_json("blocked"),
        ]
    )
    graph = build_graph(model=model)  # no checkpointer
    final = await graph.ainvoke(OKRState(intent="Reach PMF in SMB"))

    # Legacy fallback: awaiting_human is set, no interrupt fired
    assert final.get("awaiting_human") is not None
    assert final["awaiting_human"].reason == "alignment_conflict"
