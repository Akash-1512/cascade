"""Repository for the :class:`Team` aggregate."""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from cascade.domain.identity import Team, TeamCreate
from cascade.storage.models import TeamORM
from cascade.storage.repositories import (
    BaseRepository,
    DuplicateError,
    NotFoundError,
)


class TeamRepository(BaseRepository[Team]):
    """Persistence for :class:`Team`."""

    async def create(self, payload: TeamCreate) -> Team:
        """Persist a new team. Raises :class:`DuplicateError` on slug collision."""
        orm = TeamORM(
            name=payload.name,
            slug=payload.slug,
            parent_team_id=payload.parent_team_id,
        )
        self._session.add(orm)
        try:
            await self._session.flush()
        except IntegrityError as exc:
            await self._session.rollback()
            raise DuplicateError("team", "slug", payload.slug) from exc
        await self._session.refresh(orm)
        return self._to_domain(orm)

    async def get(self, team_id: UUID) -> Team:
        """Fetch by primary key. Raises :class:`NotFoundError` if absent."""
        orm = await self._session.get(TeamORM, team_id)
        if orm is None:
            raise NotFoundError("team", team_id)
        return self._to_domain(orm)

    async def get_by_slug(self, slug: str) -> Team:
        """Fetch by URL-safe slug."""
        result = await self._session.execute(select(TeamORM).where(TeamORM.slug == slug))
        orm = result.scalar_one_or_none()
        if orm is None:
            raise NotFoundError("team", slug)
        return self._to_domain(orm)

    async def list_children(self, parent_id: UUID) -> list[Team]:
        """All teams whose ``parent_team_id`` matches ``parent_id``."""
        result = await self._session.execute(
            select(TeamORM).where(TeamORM.parent_team_id == parent_id).order_by(TeamORM.name)
        )
        return [self._to_domain(row) for row in result.scalars().all()]

    @staticmethod
    def _to_domain(orm: TeamORM) -> Team:
        return Team(
            id=orm.id,
            name=orm.name,
            slug=orm.slug,
            parent_team_id=orm.parent_team_id,
            created_at=orm.created_at,
            updated_at=orm.updated_at,
        )
