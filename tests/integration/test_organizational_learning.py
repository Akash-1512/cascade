"""Integration tests for :class:`OrganizationalLearningRepository`."""

from __future__ import annotations

from uuid import uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from cascade.domain.organizational_learning import OrganizationalLearningCreate
from cascade.storage.repositories.organizational_learning import (
    OrganizationalLearningRepository,
)
from tests.integration.factories import seed_team


def _payload(team_id, *, quarter: str = "2026Q2", **overrides) -> OrganizationalLearningCreate:
    defaults = {
        "team_id": team_id,
        "quarter": quarter,
        "title": "Underestimated dependency on data team",
        "description": (
            "Multiple OKRs slipped because data instrumentation took longer "
            "than planned in three of four cases."
        ),
        "category": "estimation",
        "occurrences": 3,
        "affected_okr_ids": [str(uuid4()), str(uuid4())],
    }
    defaults.update(overrides)
    return OrganizationalLearningCreate(**defaults)


@pytest.mark.integration
async def test_create_persists_learning(session: AsyncSession) -> None:
    team = await seed_team(session)
    repo = OrganizationalLearningRepository(session)

    learning = await repo.create(_payload(team.id))

    assert learning.id is not None
    assert learning.team_id == team.id
    assert learning.category == "estimation"
    assert learning.occurrences == 3
    assert len(learning.affected_okr_ids) == 2


@pytest.mark.integration
async def test_list_for_team_filters_by_quarter(session: AsyncSession) -> None:
    team = await seed_team(session)
    repo = OrganizationalLearningRepository(session)

    await repo.create(_payload(team.id, quarter="2026Q1"))
    await repo.create(_payload(team.id, quarter="2026Q2"))
    await repo.create(_payload(team.id, quarter="2026Q2", title="Second Q2 theme"))
    await session.flush()

    q2 = await repo.list_for_team(team.id, quarter="2026Q2")
    assert len(q2) == 2

    q1 = await repo.list_for_team(team.id, quarter="2026Q1")
    assert len(q1) == 1


@pytest.mark.integration
async def test_list_for_team_filters_by_category(session: AsyncSession) -> None:
    team = await seed_team(session)
    repo = OrganizationalLearningRepository(session)

    await repo.create(_payload(team.id, category="estimation"))
    await repo.create(_payload(team.id, category="process", title="Process theme"))
    await repo.create(_payload(team.id, category="execution", title="Execution theme"))
    await session.flush()

    estimation = await repo.list_for_team(team.id, category="estimation")
    assert len(estimation) == 1
    assert estimation[0].category == "estimation"


@pytest.mark.integration
async def test_supersedes_relationship_preserves_audit_trail(
    session: AsyncSession,
) -> None:
    """A new learning that supersedes an old one carries the link."""
    team = await seed_team(session)
    repo = OrganizationalLearningRepository(session)

    original = await repo.create(_payload(team.id, quarter="2026Q1"))
    successor = await repo.create(
        _payload(
            team.id,
            quarter="2026Q2",
            title="Resolved: dependency on data team",
            supersedes_id=original.id,
        )
    )

    assert successor.supersedes_id == original.id
    # The original is still retrievable
    fetched = await repo.get(original.id)
    assert fetched is not None
    assert fetched.id == original.id


@pytest.mark.integration
async def test_get_returns_none_for_unknown_id(session: AsyncSession) -> None:
    repo = OrganizationalLearningRepository(session)
    result = await repo.get(uuid4())
    assert result is None


@pytest.mark.integration
async def test_list_orders_newest_first(session: AsyncSession) -> None:
    """SQLite's CURRENT_TIMESTAMP has 1-second resolution; we use longer sleeps
    to verify ordering. CI's Postgres-backed run uses sub-millisecond timestamps
    and would pass this even without sleeps."""
    import asyncio

    team = await seed_team(session)
    repo = OrganizationalLearningRepository(session)

    first = await repo.create(_payload(team.id, title="First created"))
    await session.commit()
    await asyncio.sleep(1.1)
    second = await repo.create(_payload(team.id, title="Second created"))
    await session.commit()
    await asyncio.sleep(1.1)
    third = await repo.create(_payload(team.id, title="Third created"))
    await session.commit()

    results = await repo.list_for_team(team.id)
    assert len(results) == 3
    assert results[0].id == third.id
    assert results[1].id == second.id
    assert results[2].id == first.id
