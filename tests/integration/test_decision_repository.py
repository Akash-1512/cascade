"""Integration tests for :class:`DecisionRepository`."""

from __future__ import annotations

from uuid import uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from cascade.domain.decision import Alternative, DecisionCreate, Evidence
from cascade.domain.enums import DecisionEventType, MetricType
from cascade.domain.okr import KeyResultCreate, ObjectiveCreate, Quarter
from cascade.storage.repositories import NotFoundError, RepositoryError
from cascade.storage.repositories.decision import DecisionRepository
from cascade.storage.repositories.objective import ObjectiveRepository
from tests.integration.factories import seed_team, seed_user


async def _seed_objective(session: AsyncSession) -> tuple:
    team = await seed_team(session)
    user = await seed_user(session, team_id=team.id)
    obj_repo = ObjectiveRepository(session)
    obj = await obj_repo.create(
        ObjectiveCreate(
            title="Reach NPS of 45 across the SMB cohort this quarter",
            team_id=team.id,
            quarter=Quarter(year=2026, quarter=2),
            key_results=[
                KeyResultCreate(
                    description="Lift weekly active accounts from 200 to 800",
                    metric_type=MetricType.NUMBER,
                    baseline_value=200,
                    target_value=800,
                    current_value=200,
                ),
            ],
        ),
        owner_id=user.id,
    )
    return user, obj


@pytest.mark.integration
async def test_create_with_full_context(session: AsyncSession) -> None:
    user, obj = await _seed_objective(session)
    repo = DecisionRepository(session)

    decision = await repo.create(
        DecisionCreate(
            event_type=DecisionEventType.OBJECTIVE_COMMIT,
            objective_id=obj.id,
            summary="Committed Q2 SMB expansion objective after pipeline review",
            alternatives=[
                Alternative(
                    option="Pursue enterprise expansion instead",
                    reason_rejected="No SDR coverage for enterprise motion this quarter",
                ),
                Alternative(
                    option="Hold the prior quarter's targets",
                    reason_rejected="Doesn't reflect product-market fit signals from Q1",
                ),
            ],
            chosen="SMB expansion with weekly review cadence",
            tradeoff="Defers enterprise investment to Q3",
            evidence=[
                Evidence(
                    source="Pipeline review Apr 14",
                    claim="SMB conversion rate improved 18% quarter over quarter",
                    link="https://example.com/pipeline-q1",
                ),
            ],
        ),
        actor_id=user.id,
    )
    assert decision.event_type == DecisionEventType.OBJECTIVE_COMMIT
    assert len(decision.alternatives) == 2
    assert decision.tradeoff is not None
    assert decision.evidence[0].link is not None


@pytest.mark.integration
async def test_create_minimal(session: AsyncSession) -> None:
    user, obj = await _seed_objective(session)
    repo = DecisionRepository(session)

    decision = await repo.create(
        DecisionCreate(
            event_type=DecisionEventType.OBJECTIVE_COMMIT,
            objective_id=obj.id,
            summary="Committed initial draft after team review",
            chosen="Proceed as drafted",
        ),
        actor_id=user.id,
    )
    assert decision.alternatives == []
    assert decision.evidence == []
    assert decision.tradeoff is None


@pytest.mark.integration
async def test_get_returns_decision(session: AsyncSession) -> None:
    user, obj = await _seed_objective(session)
    repo = DecisionRepository(session)
    created = await repo.create(
        DecisionCreate(
            event_type=DecisionEventType.OBJECTIVE_COMMIT,
            objective_id=obj.id,
            summary="Initial commitment for the quarter",
            chosen="Proceed",
        ),
        actor_id=user.id,
    )
    fetched = await repo.get(created.id)
    assert fetched.id == created.id


@pytest.mark.integration
async def test_get_missing_raises(session: AsyncSession) -> None:
    repo = DecisionRepository(session)
    with pytest.raises(NotFoundError):
        await repo.get(uuid4())


@pytest.mark.integration
async def test_list_for_objective_orders_newest_first(
    session: AsyncSession,
) -> None:
    user, obj = await _seed_objective(session)
    repo = DecisionRepository(session)

    summaries = ["First commit", "Reframed scope", "Lowered Q2 target"]
    for summary in summaries:
        await repo.create(
            DecisionCreate(
                event_type=DecisionEventType.OBJECTIVE_COMMIT,
                objective_id=obj.id,
                summary=f"{summary} — captured during the Monday review",
                chosen="As stated",
            ),
            actor_id=user.id,
        )

    decisions = await repo.list_for_objective(obj.id)
    assert len(decisions) == 3
    # Newest first: the third we created should appear first
    assert decisions[0].summary.startswith("Lowered Q2 target")


@pytest.mark.integration
async def test_list_for_key_result(session: AsyncSession) -> None:
    user, obj = await _seed_objective(session)
    kr_id = obj.key_results[0].id
    repo = DecisionRepository(session)

    await repo.create(
        DecisionCreate(
            event_type=DecisionEventType.KR_TARGET_CHANGE,
            objective_id=obj.id,
            key_result_id=kr_id,
            summary="Lowered target from 800 to 600 after pipeline review",
            chosen="Set to 600",
        ),
        actor_id=user.id,
    )
    # An OKR-level decision that should not be returned
    await repo.create(
        DecisionCreate(
            event_type=DecisionEventType.OBJECTIVE_COMMIT,
            objective_id=obj.id,
            summary="Initial commit at the quarter start",
            chosen="As drafted",
        ),
        actor_id=user.id,
    )

    decisions = await repo.list_for_key_result(kr_id)
    assert len(decisions) == 1
    assert decisions[0].event_type == DecisionEventType.KR_TARGET_CHANGE


@pytest.mark.integration
async def test_link_decisions(session: AsyncSession) -> None:
    user, obj = await _seed_objective(session)
    repo = DecisionRepository(session)

    cause = await repo.create(
        DecisionCreate(
            event_type=DecisionEventType.RISK_INTERVENTION,
            objective_id=obj.id,
            summary="Flagged at-risk based on velocity slowdown",
            chosen="Convene weekly review",
        ),
        actor_id=user.id,
    )
    effect = await repo.create(
        DecisionCreate(
            event_type=DecisionEventType.KR_TARGET_CHANGE,
            objective_id=obj.id,
            summary="Lowered target after risk review",
            chosen="Set to 600",
        ),
        actor_id=user.id,
    )

    await repo.link(effect.id, cause.id, relation="caused_by")
    # Idempotency check would require a unique constraint — we only check it ran
    # without raising, leaving link inspection for later phases.


@pytest.mark.integration
async def test_link_invalid_relation_raises(session: AsyncSession) -> None:
    user, obj = await _seed_objective(session)
    repo = DecisionRepository(session)

    a = await repo.create(
        DecisionCreate(
            event_type=DecisionEventType.OBJECTIVE_COMMIT,
            objective_id=obj.id,
            summary="First decision recorded",
            chosen="Yes",
        ),
        actor_id=user.id,
    )
    b = await repo.create(
        DecisionCreate(
            event_type=DecisionEventType.OBJECTIVE_REFRAME,
            objective_id=obj.id,
            summary="Second decision recorded",
            chosen="Reframe",
        ),
        actor_id=user.id,
    )

    with pytest.raises(ValueError, match="invalid relation"):
        await repo.link(a.id, b.id, relation="not-a-real-relation")


@pytest.mark.integration
async def test_link_self_raises(session: AsyncSession) -> None:
    user, obj = await _seed_objective(session)
    repo = DecisionRepository(session)

    d = await repo.create(
        DecisionCreate(
            event_type=DecisionEventType.OBJECTIVE_COMMIT,
            objective_id=obj.id,
            summary="A decision that cannot link to itself",
            chosen="Yes",
        ),
        actor_id=user.id,
    )

    with pytest.raises(ValueError, match="cannot link to itself"):
        await repo.link(d.id, d.id, relation="caused_by")


@pytest.mark.integration
async def test_link_missing_decision_raises_repository_error(
    session: AsyncSession,
) -> None:
    user, obj = await _seed_objective(session)
    repo = DecisionRepository(session)

    real = await repo.create(
        DecisionCreate(
            event_type=DecisionEventType.OBJECTIVE_COMMIT,
            objective_id=obj.id,
            summary="A real decision in the database",
            chosen="Yes",
        ),
        actor_id=user.id,
    )

    with pytest.raises(RepositoryError):
        await repo.link(real.id, uuid4(), relation="caused_by")
