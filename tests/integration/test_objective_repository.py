"""Integration tests for :class:`ObjectiveRepository`."""

from __future__ import annotations

from uuid import uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from cascade.domain.enums import KeyResultStatus, MetricType, ObjectiveStatus
from cascade.domain.okr import (
    KeyResultCreate,
    ObjectiveCreate,
    Quarter,
)
from cascade.storage.repositories import NotFoundError
from cascade.storage.repositories.objective import ObjectiveRepository
from tests.integration.factories import seed_team, seed_user


@pytest.mark.integration
async def test_create_persists_objective_with_key_results(
    session: AsyncSession,
) -> None:
    team = await seed_team(session)
    user = await seed_user(session, team_id=team.id)
    repo = ObjectiveRepository(session)

    payload = ObjectiveCreate(
        title="Reach product-market fit in the SMB segment",
        description="Q2 focus on SMB conversion",
        team_id=team.id,
        quarter=Quarter(year=2026, quarter=2),
        key_results=[
            KeyResultCreate(
                description="Increase weekly active accounts from 200 to 800",
                metric_type=MetricType.NUMBER,
                baseline_value=200,
                target_value=800,
                current_value=200,
                weight=2.0,
            ),
            KeyResultCreate(
                description="Reach NPS of 45 across the SMB cohort",
                metric_type=MetricType.NUMBER,
                baseline_value=32,
                target_value=45,
                current_value=32,
            ),
        ],
    )
    obj = await repo.create(payload, owner_id=user.id)
    assert obj.title.startswith("Reach product-market fit")
    assert obj.status == ObjectiveStatus.DRAFT
    assert len(obj.key_results) == 2
    assert {kr.weight for kr in obj.key_results} == {1.0, 2.0}


@pytest.mark.integration
async def test_create_uses_baseline_when_current_omitted(
    session: AsyncSession,
) -> None:
    team = await seed_team(session)
    user = await seed_user(session, team_id=team.id)
    repo = ObjectiveRepository(session)

    payload = ObjectiveCreate(
        title="Ship the redesigned onboarding flow",
        team_id=team.id,
        quarter=Quarter(year=2026, quarter=2),
        key_results=[
            KeyResultCreate(
                description="Complete five usability tests with target users",
                metric_type=MetricType.MILESTONE,
                baseline_value=0,
                target_value=5,
                current_value=None,
            ),
        ],
    )
    obj = await repo.create(payload, owner_id=user.id)
    assert obj.key_results[0].current_value == 0


@pytest.mark.integration
async def test_get_loads_key_results(session: AsyncSession) -> None:
    team = await seed_team(session)
    user = await seed_user(session, team_id=team.id)
    repo = ObjectiveRepository(session)

    payload = ObjectiveCreate(
        title="Improve activation rate among new accounts",
        team_id=team.id,
        quarter=Quarter(year=2026, quarter=3),
        key_results=[
            KeyResultCreate(
                description="Lift first-week activation from 32% to 50%",
                metric_type=MetricType.PERCENTAGE,
                baseline_value=32,
                target_value=50,
                current_value=32,
            ),
        ],
    )
    created = await repo.create(payload, owner_id=user.id)

    fetched = await repo.get(created.id)
    assert fetched.id == created.id
    assert len(fetched.key_results) == 1
    assert fetched.key_results[0].metric_type == MetricType.PERCENTAGE


@pytest.mark.integration
async def test_get_missing_raises_not_found(session: AsyncSession) -> None:
    repo = ObjectiveRepository(session)
    with pytest.raises(NotFoundError):
        await repo.get(uuid4())


@pytest.mark.integration
async def test_list_for_team_filters_by_quarter(session: AsyncSession) -> None:
    team = await seed_team(session)
    user = await seed_user(session, team_id=team.id)
    repo = ObjectiveRepository(session)

    q2 = Quarter(year=2026, quarter=2)
    q3 = Quarter(year=2026, quarter=3)

    for quarter in (q2, q2, q3):
        await repo.create(
            ObjectiveCreate(
                title=f"Objective for {quarter}",
                team_id=team.id,
                quarter=quarter,
            ),
            owner_id=user.id,
        )

    all_objectives = await repo.list_for_team(team.id)
    assert len(all_objectives) == 3

    q2_only = await repo.list_for_team(team.id, quarter=q2)
    assert len(q2_only) == 2
    assert all(o.quarter == q2 for o in q2_only)


@pytest.mark.integration
async def test_update_status_transitions(session: AsyncSession) -> None:
    team = await seed_team(session)
    user = await seed_user(session, team_id=team.id)
    repo = ObjectiveRepository(session)

    obj = await repo.create(
        ObjectiveCreate(
            title="Become the most loved tool in our category",
            team_id=team.id,
            quarter=Quarter(year=2026, quarter=2),
        ),
        owner_id=user.id,
    )
    assert obj.status == ObjectiveStatus.DRAFT

    activated = await repo.update_status(obj.id, ObjectiveStatus.ACTIVE)
    assert activated.status == ObjectiveStatus.ACTIVE

    achieved = await repo.update_status(obj.id, ObjectiveStatus.ACHIEVED)
    assert achieved.status == ObjectiveStatus.ACHIEVED


@pytest.mark.integration
async def test_add_key_result(session: AsyncSession) -> None:
    team = await seed_team(session)
    user = await seed_user(session, team_id=team.id)
    repo = ObjectiveRepository(session)

    obj = await repo.create(
        ObjectiveCreate(
            title="Establish thought leadership in our space",
            team_id=team.id,
            quarter=Quarter(year=2026, quarter=2),
        ),
        owner_id=user.id,
    )
    kr = await repo.add_key_result(
        obj.id,
        KeyResultCreate(
            description="Publish six in-depth technical articles this quarter",
            metric_type=MetricType.MILESTONE,
            baseline_value=0,
            target_value=6,
            current_value=0,
        ),
        owner_id=user.id,
    )
    assert kr.objective_id == obj.id
    assert kr.status == KeyResultStatus.NOT_STARTED

    refreshed = await repo.get(obj.id)
    assert len(refreshed.key_results) == 1
