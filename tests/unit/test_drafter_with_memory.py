"""Tests verifying the Drafter pulls memory context when a ContextBuilder is wired in."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from uuid import uuid4

import pytest

from cascade.agents.drafter import draft_objective
from cascade.agents.llm import FakeChatModel
from cascade.domain.decision import Decision
from cascade.domain.enums import DecisionEventType
from cascade.memory.context_builder import ContextBuilder
from cascade.memory.fakes import StaticRetriever
from cascade.memory.types import MemoryChunk, RetrievedChunk
from tests.unit.test_agents import GOOD_PROPOSAL_JSON


def _decision(**overrides: object) -> Decision:
    defaults: dict[str, object] = {
        "event_type": DecisionEventType.OBJECTIVE_COMMIT,
        "objective_id": uuid4(),
        "summary": "Lowered Q1 SMB target from 800 to 600 after pipeline review",
        "chosen": "Set target to 600",
        "tradeoff": "Defers ambition to fund SDR hiring runway",
        "actor_id": uuid4(),
        "created_at": datetime(2026, 4, 14, tzinfo=UTC),
    }
    defaults.update(overrides)
    return Decision(**defaults)  # type: ignore[arg-type]


class _FakeDecisionRepo:
    """Minimal stand-in for DecisionRepository.list_for_objective."""

    def __init__(self, decisions: list[Decision]) -> None:
        self._decisions = decisions

    async def list_for_objective(self, objective_id, *, limit: int = 100):  # type: ignore[no-untyped-def]
        return self._decisions[:limit]


@pytest.mark.unit
async def test_drafter_pulls_memory_when_context_builder_wired() -> None:
    """When a ContextBuilder is provided with okr_id, decisions reach the prompt."""
    okr_id = uuid4()
    decisions = [_decision(objective_id=okr_id)]

    retriever = StaticRetriever(
        results=[
            RetrievedChunk(
                chunk=MemoryChunk(
                    id="chunk-1",
                    text="Three weeks ago we reduced the SMB target after a pipeline review",
                    metadata={"kind": "drafting"},
                ),
                score=0.9,
                source="rerank",
            )
        ]
    )
    builder = ContextBuilder(retriever=retriever, decision_repository=_FakeDecisionRepo(decisions))

    model = FakeChatModel(responses=[GOOD_PROPOSAL_JSON])
    await draft_objective(
        intent="Reach PMF in SMB",
        model=model,
        context_builder=builder,
        okr_id=okr_id,
    )

    # Assert the rendered prompt mentioned the decision and the chunk
    sent_to_model = str(model.call_log[0])
    assert "Lowered Q1 SMB target from 800 to 600" in sent_to_model
    assert "Defers ambition to fund SDR hiring runway" in sent_to_model
    assert "Three weeks ago we reduced the SMB target" in sent_to_model

    # Retriever was called with the okr_id
    assert len(retriever.calls) == 1
    assert retriever.calls[0].okr_id == okr_id


@pytest.mark.unit
async def test_drafter_works_without_context_builder() -> None:
    """No regression — calling without a builder still works."""
    model = FakeChatModel(responses=[GOOD_PROPOSAL_JSON])
    proposal = await draft_objective(intent="Reach PMF in SMB", model=model)
    assert proposal.title.startswith("Reach product-market fit")


@pytest.mark.unit
async def test_drafter_skips_memory_section_when_no_context() -> None:
    """When the builder returns empty context, the prompt has no memory section."""
    builder = ContextBuilder(
        retriever=StaticRetriever(results=[]),
        decision_repository=None,
    )
    model = FakeChatModel(responses=[GOOD_PROPOSAL_JSON])
    await draft_objective(
        intent="Reach PMF in SMB",
        model=model,
        context_builder=builder,
    )
    sent_to_model = str(model.call_log[0])
    assert "Relevant memory" not in sent_to_model


@pytest.mark.unit
async def test_drafter_passes_team_and_quarter_to_retriever() -> None:
    team_id = uuid4()
    retriever = StaticRetriever(results=[])
    builder = ContextBuilder(retriever=retriever, decision_repository=None)
    model = FakeChatModel(responses=[GOOD_PROPOSAL_JSON])

    await draft_objective(
        intent="Reach PMF in SMB",
        model=model,
        context_builder=builder,
        team_id=team_id,
        quarter="2026Q2",
    )
    assert retriever.calls[0].team_id == team_id
    assert retriever.calls[0].quarter == "2026Q2"


# Re-export so the GOOD_PROPOSAL_JSON import above isn't unused
_ = json
