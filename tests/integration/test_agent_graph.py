"""Integration tests for the agent graph with a fake LLM.

These tests exercise the full drafter↔critic loop including iteration accounting,
HITL escalation, and state persistence across nodes. They run with the
:class:`FakeChatModel` so they're hermetic and fast — production runs against Groq.
"""

from __future__ import annotations

import json

import pytest

from cascade.agents.contracts import HumanInterrupt, ProposedObjective
from cascade.agents.llm import FakeChatModel
from cascade.orchestrator.graph import build_graph
from cascade.orchestrator.state import OKRState
from cascade.orchestrator.supervisor import ITERATION_CAP


def _good_proposal_json() -> str:
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
                },
                {
                    "description": "Reach NPS of 45 across the SMB cohort",
                    "metric_type": "number",
                    "baseline_value": 32,
                    "target_value": 45,
                    "current_value": 32,
                    "unit": "NPS",
                    "weight": 1.0,
                },
            ],
        }
    )


def _critique_json(verdict: str, min_score: float = 0.85) -> str:
    return json.dumps(
        {
            "specificity": {"score": min_score, "reasoning": "ok"},
            "measurability": {"score": 0.9, "reasoning": "ok"},
            "ambition": {"score": 0.85, "reasoning": "ok"},
            "structure": {"score": 0.9, "reasoning": "ok"},
            "vague_phrases": [],
            "verdict": verdict,
            "suggestions": [] if verdict == "pass" else ["Sharpen the SMB segment definition"],
        }
    )


def _alignment_json(verdict: str = "aligned", vertical: float = 0.9) -> str:
    return json.dumps(
        {
            "vertical_score": vertical,
            "vertical_reasoning": "Direct contribution to parent",
            "conflicts": [],
            "verdict": verdict,
            "suggestions": [],
        }
    )


@pytest.mark.integration
async def test_graph_passes_critique_and_alignment_on_first_run() -> None:
    """Drafter → Critic (pass) → Aligner (aligned) terminates the run."""
    model = FakeChatModel(
        responses=[
            _good_proposal_json(),
            _critique_json("pass"),
            _alignment_json("aligned"),
        ]
    )
    graph = build_graph(model=model)
    initial = OKRState(intent="Reach product-market fit in SMB", trace_id="t1")

    final = await graph.ainvoke(initial)

    assert final["proposal"] is not None
    assert isinstance(final["proposal"], ProposedObjective)
    assert final["critique"].verdict == "pass"
    assert final["alignment"].verdict == "aligned"
    assert len(final["iterations"]) == 1
    assert final.get("awaiting_human") is None


@pytest.mark.integration
async def test_graph_loops_through_critic_then_aligns() -> None:
    """Drafter → Critic (revision) → Drafter → Critic (pass) → Aligner (aligned)."""
    model = FakeChatModel(
        responses=[
            _good_proposal_json(),
            _critique_json("needs_revision", min_score=0.5),
            _good_proposal_json(),
            _critique_json("pass"),
            _alignment_json("aligned"),
        ]
    )
    graph = build_graph(model=model)
    initial = OKRState(intent="Reach PMF in SMB", trace_id="t2")

    final = await graph.ainvoke(initial)

    assert final["critique"].verdict == "pass"
    assert final["alignment"].verdict == "aligned"
    assert len(final["iterations"]) == 2
    assert final.get("awaiting_human") is None


@pytest.mark.integration
async def test_graph_escalates_on_alignment_blocked() -> None:
    """Critic passes but Aligner finds a blocking conflict — escalate to human."""
    model = FakeChatModel(
        responses=[
            _good_proposal_json(),
            _critique_json("pass"),
            _alignment_json("blocked", vertical=0.3),
        ]
    )
    graph = build_graph(model=model)
    final = await graph.ainvoke(OKRState(intent="x", trace_id="t-block"))

    assert final["awaiting_human"] is not None
    assert final["awaiting_human"].reason == "alignment_conflict"


@pytest.mark.integration
async def test_graph_escalates_on_reject() -> None:
    """A reject verdict on the first critique escalates to a human immediately."""
    model = FakeChatModel(
        responses=[
            _good_proposal_json(),
            _critique_json("reject", min_score=0.2),
        ]
    )
    graph = build_graph(model=model)
    initial = OKRState(intent="x", trace_id="t3")

    final = await graph.ainvoke(initial)

    assert final["awaiting_human"] is not None
    assert isinstance(final["awaiting_human"], HumanInterrupt)
    assert final["awaiting_human"].reason == "fundamental_reject"


@pytest.mark.integration
async def test_graph_escalates_at_iteration_cap() -> None:
    """``ITERATION_CAP`` revisions in a row escalate to a human."""
    responses: list[str] = []
    for _ in range(ITERATION_CAP):
        responses.append(_good_proposal_json())
        responses.append(_critique_json("needs_revision", min_score=0.5))
    model = FakeChatModel(responses=responses)
    graph = build_graph(model=model)

    initial = OKRState(intent="x", trace_id="t4")
    final = await graph.ainvoke(initial)

    assert final["awaiting_human"] is not None
    assert final["awaiting_human"].reason == "iteration_cap_reached"
    assert len(final["iterations"]) == ITERATION_CAP


@pytest.mark.integration
async def test_graph_iterations_carry_proposal_and_critique() -> None:
    """Each iteration's proposal+critique pair is preserved on state."""
    model = FakeChatModel(
        responses=[
            _good_proposal_json(),
            _critique_json("needs_revision", min_score=0.5),
            _good_proposal_json(),
            _critique_json("pass"),
            _alignment_json("aligned"),
        ]
    )
    graph = build_graph(model=model)
    final = await graph.ainvoke(OKRState(intent="x", trace_id="t5"))

    iterations = final["iterations"]
    assert iterations[0].iteration == 1
    assert iterations[0].critique.verdict == "needs_revision"
    assert iterations[1].iteration == 2
    assert iterations[1].critique.verdict == "pass"
