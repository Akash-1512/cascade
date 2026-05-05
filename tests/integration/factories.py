"""Helpers for seeding integration-test data.

These helpers create raw ORM rows. Tests use them to set up prerequisites cheaply,
then exercise the repositories that are actually under test.
"""

from __future__ import annotations

from uuid import UUID, uuid4

from sqlalchemy.ext.asyncio import AsyncSession

from cascade.domain.enums import UserRole
from cascade.storage.models import TeamORM, UserORM


async def seed_team(
    session: AsyncSession,
    *,
    name: str = "Product",
    slug: str = "product",
    parent_team_id: UUID | None = None,
) -> TeamORM:
    """Create and flush a TeamORM row, returning the persisted instance."""
    team = TeamORM(name=name, slug=slug, parent_team_id=parent_team_id)
    session.add(team)
    await session.flush()
    await session.refresh(team)
    return team


async def seed_user(
    session: AsyncSession,
    *,
    team_id: UUID,
    email: str | None = None,
    role: UserRole = UserRole.CONTRIBUTOR,
    full_name: str = "Test User",
) -> UserORM:
    """Create and flush a UserORM row."""
    user = UserORM(
        email=email or f"{uuid4()}@example.com",
        full_name=full_name,
        role=role,
        team_id=team_id,
        is_active=True,
        password_hash="not-a-real-hash",
    )
    session.add(user)
    await session.flush()
    await session.refresh(user)
    return user
