"""Live end-to-end smoke tests against a real LLM provider.

These tests require ``GROQ_API_KEY`` and are skipped otherwise. They are not part of
the default CI run — they protect the production code path against silent regressions
when LangGraph or langchain-groq update.
"""

from __future__ import annotations

import os

import pytest

from cascade.agents.contracts import ProposedObjective
from cascade.agents.llm import get_chat_model
from cascade.orchestrator.graph import build_graph
from cascade.orchestrator.state import OKRState


pytestmark = pytest.mark.skipif(
    not os.environ.get("GROQ_API_KEY"),
    reason="GROQ_API_KEY not set; skipping live smoke tests",
)


@pytest.mark.e2e
@pytest.mark.slow
async def test_live_drafter_critic_loop() -> None:
    """The full graph runs end-to-end against Groq and produces a structured result."""
    model = get_chat_model()
    graph = build_graph(model=model)
    initial = OKRState(
        intent=(
            "We want to win in the SMB segment this quarter. We need to convert more "
            "trial users and lift product engagement so we have a strong base going "
            "into Q3."
        ),
        trace_id="live-smoke-1",
    )

    final = await graph.ainvoke(initial)

    assert final["proposal"] is not None
    assert isinstance(final["proposal"], ProposedObjective)
    assert 2 <= len(final["proposal"].key_results) <= 5
    assert final["critique"] is not None
    # Either it converged or it escalated — both are acceptable terminal states.
    assert final["critique"].verdict in {"pass", "needs_revision", "reject"}
