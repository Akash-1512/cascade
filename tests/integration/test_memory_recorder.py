"""Integration tests for :class:`MemoryRecorder`.

These verify that committing a drafted Objective produces all three artefacts in
the right order and with the right cross-references: the relational Objective row,
the structured Decision row, and the conversational chunks linked back to both.
"""

from __future__ import annotations

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from cascade.agents.contracts import (
    CritiqueResult,
    DimensionScore,
    DraftIteration,
    ProposedKeyResult,
    ProposedObjective,
)
from cascade.domain.enums import DecisionEventType, MetricType
from cascade.domain.okr import Quarter
from cascade.memory.fakes import HashEmbedder, InMemoryStore
from cascade.memory.recorder import MemoryRecorder
from cascade.storage.repositories.decision import DecisionRepository
from cascade.storage.repositories.objective import ObjectiveRepository
from tests.integration.factories import seed_team, seed_user


def _proposal(title: str = "Reach product-market fit in the SMB segment") -> ProposedObjective:
    return ProposedObjective(
        title=title,
        description="Q2 focus on SMB conversion across two channels",
        key_results=[
            ProposedKeyResult(
                description="Lift weekly active accounts from 200 to 800",
                metric_type=MetricType.NUMBER,
                baseline_value=200,
                target_value=800,
                current_value=200,
                unit="accounts",
            ),
            ProposedKeyResult(
                description="Improve trial-to-paid conversion from 12% to 22%",
                metric_type=MetricType.PERCENTAGE,
                baseline_value=12,
                target_value=22,
                current_value=12,
            ),
        ],
    )


def _critique(verdict: str = "pass", min_score: float = 0.85) -> CritiqueResult:
    return CritiqueResult(
        specificity=DimensionScore(score=min_score, reasoning="r"),
        measurability=DimensionScore(score=0.9, reasoning="r"),
        ambition=DimensionScore(score=0.85, reasoning="r"),
        structure=DimensionScore(score=0.9, reasoning="r"),
        vague_phrases=[],
        verdict=verdict,  # type: ignore[arg-type]
        suggestions=[] if verdict == "pass" else ["Sharpen the segment definition"],
    )


@pytest.mark.integration
async def test_commit_persists_objective_decision_and_transcript(
    session: AsyncSession,
) -> None:
    team = await seed_team(session)
    user = await seed_user(session, team_id=team.id)

    proposal = _proposal()
    iterations = [
        DraftIteration(proposal=proposal, critique=_critique("pass"), iteration=1),
    ]

    store = InMemoryStore(HashEmbedder())
    recorder = MemoryRecorder(
        objectives=ObjectiveRepository(session),
        decisions=DecisionRepository(session),
        memory_store=store,
    )

    outcome = await recorder.commit_drafted_objective(
        proposal=proposal,
        iterations=iterations,
        team_id=team.id,
        quarter=Quarter(year=2026, quarter=2),
        actor_id=user.id,
    )

    # Objective row was created with both KRs
    assert outcome.objective.team_id == team.id
    assert len(outcome.objective.key_results) == 2

    # Decision references the new Objective
    assert outcome.decision.objective_id == outcome.objective.id
    assert outcome.decision.event_type == DecisionEventType.OBJECTIVE_COMMIT
    assert outcome.decision.alternatives == []  # single iteration, no alternatives
    assert outcome.decision.evidence  # critique scores captured

    # One chunk per iteration
    assert len(outcome.chunk_ids) == 1
    chunk = await store.get(outcome.chunk_ids[0])
    assert chunk is not None
    assert chunk.metadata["okr_id"] == str(outcome.objective.id)
    assert chunk.metadata["decision_id"] == str(outcome.decision.id)
    assert chunk.metadata["kind"] == "drafting"


@pytest.mark.integration
async def test_commit_records_alternatives_from_iteration_history(
    session: AsyncSession,
) -> None:
    """Multi-iteration commits capture earlier drafts as alternatives."""
    team = await seed_team(session)
    user = await seed_user(session, team_id=team.id)

    iterations = [
        DraftIteration(
            proposal=_proposal(title="Vague first draft about the SMB market"),
            critique=_critique("needs_revision", 0.55),
            iteration=1,
        ),
        DraftIteration(
            proposal=_proposal(title="Slightly sharper second draft for SMB"),
            critique=_critique("needs_revision", 0.65),
            iteration=2,
        ),
        DraftIteration(
            proposal=_proposal(),
            critique=_critique("pass"),
            iteration=3,
        ),
    ]

    store = InMemoryStore(HashEmbedder())
    recorder = MemoryRecorder(
        objectives=ObjectiveRepository(session),
        decisions=DecisionRepository(session),
        memory_store=store,
    )

    outcome = await recorder.commit_drafted_objective(
        proposal=iterations[-1].proposal,
        iterations=iterations,
        team_id=team.id,
        quarter=Quarter(year=2026, quarter=2),
        actor_id=user.id,
    )

    # Two earlier drafts captured as alternatives
    assert len(outcome.decision.alternatives) == 2
    assert "Vague first draft" in outcome.decision.alternatives[0].option
    assert "Slightly sharper second draft" in outcome.decision.alternatives[1].option

    # Tradeoff captures the last revision's suggestions
    assert outcome.decision.tradeoff is not None
    assert "Sharpen the segment definition" in outcome.decision.tradeoff

    # One chunk per iteration
    assert len(outcome.chunk_ids) == 3


@pytest.mark.integration
async def test_chunks_are_searchable_after_commit(session: AsyncSession) -> None:
    """The transcript chunks land in the store and are retrievable by metadata filter."""
    team = await seed_team(session)
    user = await seed_user(session, team_id=team.id)

    proposal = _proposal()
    iterations = [DraftIteration(proposal=proposal, critique=_critique("pass"), iteration=1)]

    store = InMemoryStore(HashEmbedder())
    recorder = MemoryRecorder(
        objectives=ObjectiveRepository(session),
        decisions=DecisionRepository(session),
        memory_store=store,
    )

    outcome = await recorder.commit_drafted_objective(
        proposal=proposal,
        iterations=iterations,
        team_id=team.id,
        quarter=Quarter(year=2026, quarter=2),
        actor_id=user.id,
    )

    results = await store.search_dense(
        query="Reach product-market fit in the SMB segment",
        filters={"okr_id": str(outcome.objective.id)},
    )
    assert len(results) == 1
    assert results[0].chunk.id == outcome.chunk_ids[0]


@pytest.mark.integration
async def test_decision_listable_via_repository(session: AsyncSession) -> None:
    """Confirm the recorder's decision is retrievable through normal repository APIs."""
    team = await seed_team(session)
    user = await seed_user(session, team_id=team.id)

    proposal = _proposal()
    iterations = [DraftIteration(proposal=proposal, critique=_critique("pass"), iteration=1)]

    store = InMemoryStore(HashEmbedder())
    recorder = MemoryRecorder(
        objectives=ObjectiveRepository(session),
        decisions=DecisionRepository(session),
        memory_store=store,
    )

    outcome = await recorder.commit_drafted_objective(
        proposal=proposal,
        iterations=iterations,
        team_id=team.id,
        quarter=Quarter(year=2026, quarter=2),
        actor_id=user.id,
    )

    decisions_repo = DecisionRepository(session)
    listed = await decisions_repo.list_for_objective(outcome.objective.id)
    assert len(listed) == 1
    assert listed[0].id == outcome.decision.id
