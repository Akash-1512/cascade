"""Tests for :class:`ContextBuilder` — dynamic prompt assembly."""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

from cascade.domain.decision import Decision
from cascade.domain.enums import DecisionEventType
from cascade.memory.context_builder import ContextBuilder
from cascade.memory.fakes import StaticRetriever
from cascade.memory.types import MemoryChunk, RetrievedChunk


def _decision(**overrides: object) -> Decision:
    defaults: dict[str, object] = {
        "event_type": DecisionEventType.OBJECTIVE_COMMIT,
        "objective_id": uuid4(),
        "summary": "Committed Q2 SMB expansion objective after pipeline review",
        "chosen": "SMB expansion with weekly review cadence",
        "tradeoff": "Defers enterprise investment to Q3",
        "actor_id": uuid4(),
        "created_at": datetime(2026, 4, 14, tzinfo=UTC),
    }
    defaults.update(overrides)
    return Decision(**defaults)  # type: ignore[arg-type]


def _chunk(**overrides: object) -> RetrievedChunk:
    chunk = MemoryChunk(
        id=str(overrides.get("id", "c1")),
        text=str(overrides.get("text", "Reviewed SMB cohort metrics")),
        metadata=overrides.get("metadata", {"kind": "drafting"}),  # type: ignore[arg-type]
    )
    return RetrievedChunk(
        chunk=chunk,
        score=float(overrides.get("score", 0.85)),  # type: ignore[arg-type]
        source=str(overrides.get("source", "rerank")),
    )


@pytest.mark.unit
async def test_empty_when_no_decisions_or_chunks() -> None:
    """Cold start — no okr_id, no chunks — returns empty context."""
    retriever = StaticRetriever(results=[])
    builder = ContextBuilder(retriever=retriever, decision_repository=None)

    ctx = await builder.build(agent="drafter", intent="Reach PMF in SMB")
    assert ctx.is_empty
    assert ctx.rendered == ""
    assert ctx.token_estimate == 0


@pytest.mark.unit
async def test_renders_chunks_only_when_no_decision_repo() -> None:
    retriever = StaticRetriever(
        results=[_chunk(id="c1", text="Last week we discussed SMB onboarding")]
    )
    builder = ContextBuilder(retriever=retriever, decision_repository=None)

    ctx = await builder.build(agent="drafter", intent="SMB onboarding")
    assert "Related context from memory" in ctx.rendered
    assert "Decision history" not in ctx.rendered
    assert "Last week we discussed SMB onboarding" in ctx.rendered


@pytest.mark.unit
async def test_renders_decisions_when_okr_id_provided() -> None:
    okr_id = uuid4()
    decisions = [_decision(objective_id=okr_id)]

    decision_repo = MagicMock()
    decision_repo.list_for_objective = AsyncMock(return_value=decisions)

    retriever = StaticRetriever(results=[])
    builder = ContextBuilder(retriever=retriever, decision_repository=decision_repo)

    ctx = await builder.build(agent="drafter", intent="x", okr_id=okr_id)

    assert "Decision history" in ctx.rendered
    assert "Defers enterprise investment" in ctx.rendered  # the tradeoff
    assert ctx.decisions == decisions
    decision_repo.list_for_objective.assert_awaited_once_with(okr_id, limit=10)


@pytest.mark.unit
async def test_skips_decision_lookup_when_no_okr_id() -> None:
    decision_repo = MagicMock()
    decision_repo.list_for_objective = AsyncMock(return_value=[])

    retriever = StaticRetriever(results=[])
    builder = ContextBuilder(retriever=retriever, decision_repository=decision_repo)

    await builder.build(agent="drafter", intent="x", okr_id=None)
    decision_repo.list_for_objective.assert_not_awaited()


@pytest.mark.unit
async def test_per_agent_budgets_applied() -> None:
    """Each agent gets a different chunk budget reflected in the retriever call."""
    retriever = StaticRetriever(results=[_chunk(id=f"c{i}", text=f"chunk {i}") for i in range(20)])
    builder = ContextBuilder(retriever=retriever, decision_repository=None)

    await builder.build(agent="drafter", intent="x")
    await builder.build(agent="reflector", intent="x")
    await builder.build(agent="unknown_agent", intent="x")

    # Drafter: 3, Reflector: 8, unknown: default 3
    limits = [call.limit for call in retriever.calls]
    assert limits == [3, 8, 3]


@pytest.mark.unit
async def test_filters_propagate_to_query() -> None:
    okr_id = uuid4()
    team_id = uuid4()
    retriever = StaticRetriever(results=[])
    builder = ContextBuilder(retriever=retriever, decision_repository=None)

    await builder.build(
        agent="drafter",
        intent="some task",
        okr_id=okr_id,
        team_id=team_id,
        quarter="2026Q2",
    )

    assert len(retriever.calls) == 1
    q = retriever.calls[0]
    assert q.okr_id == okr_id
    assert q.team_id == team_id
    assert q.quarter == "2026Q2"


@pytest.mark.unit
async def test_token_estimate_increases_with_content() -> None:
    retriever = StaticRetriever(
        results=[
            _chunk(id="c1", text="A" * 200),
            _chunk(id="c2", text="B" * 200),
            _chunk(id="c3", text="C" * 200),
        ]
    )
    builder = ContextBuilder(retriever=retriever, decision_repository=None)

    ctx = await builder.build(agent="drafter", intent="x")
    # Roughly: 3 chunks x 200 chars / 4 chars-per-token = ~150 tokens
    assert ctx.token_estimate > 100
    assert ctx.token_estimate < 250
