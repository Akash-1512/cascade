"""Integration tests for :class:`TeamRepository`."""

from __future__ import annotations

from uuid import uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from cascade.domain.identity import TeamCreate
from cascade.storage.repositories import DuplicateError, NotFoundError
from cascade.storage.repositories.team import TeamRepository
from tests.integration.factories import seed_team


@pytest.mark.integration
async def test_create_persists_team(session: AsyncSession) -> None:
    repo = TeamRepository(session)
    team = await repo.create(TeamCreate(name="Engineering", slug="engineering"))
    assert team.name == "Engineering"
    assert team.slug == "engineering"
    assert team.parent_team_id is None
    assert team.created_at is not None


@pytest.mark.integration
async def test_create_duplicate_slug_raises(session: AsyncSession) -> None:
    repo = TeamRepository(session)
    await repo.create(TeamCreate(name="Engineering", slug="eng"))
    with pytest.raises(DuplicateError) as exc_info:
        await repo.create(TeamCreate(name="Different Name", slug="eng"))
    assert exc_info.value.field == "slug"
    assert exc_info.value.value == "eng"


@pytest.mark.integration
async def test_get_returns_team(session: AsyncSession) -> None:
    seeded = await seed_team(session, slug="seeded")
    repo = TeamRepository(session)
    team = await repo.get(seeded.id)
    assert team.slug == "seeded"


@pytest.mark.integration
async def test_get_missing_raises_not_found(session: AsyncSession) -> None:
    repo = TeamRepository(session)
    with pytest.raises(NotFoundError) as exc_info:
        await repo.get(uuid4())
    assert exc_info.value.entity == "team"


@pytest.mark.integration
async def test_get_by_slug(session: AsyncSession) -> None:
    seeded = await seed_team(session, slug="lookup-by-slug")
    repo = TeamRepository(session)
    team = await repo.get_by_slug("lookup-by-slug")
    assert team.id == seeded.id


@pytest.mark.integration
async def test_list_children_returns_only_direct_children(
    session: AsyncSession,
) -> None:
    parent = await seed_team(session, name="Company", slug="company")
    eng = await seed_team(session, name="Engineering", slug="eng", parent_team_id=parent.id)
    sales = await seed_team(session, name="Sales", slug="sales", parent_team_id=parent.id)
    # Grandchild — should NOT appear under parent's children
    await seed_team(session, name="Backend", slug="backend", parent_team_id=eng.id)

    repo = TeamRepository(session)
    children = await repo.list_children(parent.id)
    child_ids = {c.id for c in children}
    assert child_ids == {eng.id, sales.id}
