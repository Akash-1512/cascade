"""Repository for organizational learnings.

Append-only by design — themes are immutable. Updates happen via writing new
rows with ``supersedes_id`` set; the audit trail is part of the value.
"""

from __future__ import annotations

from typing import TYPE_CHECKING
from uuid import UUID

from sqlalchemy import select

from cascade.domain.organizational_learning import (
    OrganizationalLearning,
    OrganizationalLearningCreate,
)
from cascade.storage.models import OrganizationalLearningORM

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession


class OrganizationalLearningRepository:
    """Persistence for organizational learning themes."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create(self, payload: OrganizationalLearningCreate) -> OrganizationalLearning:
        """Persist a new learning theme."""
        row = OrganizationalLearningORM(
            team_id=payload.team_id,
            quarter=payload.quarter,
            title=payload.title,
            description=payload.description,
            category=payload.category,
            occurrences=payload.occurrences,
            affected_okr_ids=list(payload.affected_okr_ids),
            supersedes_id=payload.supersedes_id,
        )
        self._session.add(row)
        await self._session.flush()
        await self._session.refresh(row)
        return _to_domain(row)

    async def list_for_team(
        self,
        team_id: UUID,
        *,
        quarter: str | None = None,
        category: str | None = None,
        limit: int = 100,
    ) -> list[OrganizationalLearning]:
        """List learnings for a team, optionally filtered by quarter or category.

        Newest first. Useful for "what has the team learned this year",
        "what process learnings have we accumulated", and similar reads.
        """
        stmt = (
            select(OrganizationalLearningORM)
            .where(OrganizationalLearningORM.team_id == team_id)
            .order_by(OrganizationalLearningORM.created_at.desc())
            .limit(limit)
        )
        if quarter is not None:
            stmt = stmt.where(OrganizationalLearningORM.quarter == quarter)
        if category is not None:
            stmt = stmt.where(OrganizationalLearningORM.category == category)

        rows = (await self._session.execute(stmt)).scalars().all()
        return [_to_domain(r) for r in rows]

    async def get(self, learning_id: UUID) -> OrganizationalLearning | None:
        """Fetch a single learning by id, or ``None`` if not found."""
        row = await self._session.get(OrganizationalLearningORM, learning_id)
        return _to_domain(row) if row is not None else None


def _to_domain(row: OrganizationalLearningORM) -> OrganizationalLearning:
    return OrganizationalLearning(
        id=row.id,
        team_id=row.team_id,
        quarter=row.quarter,
        title=row.title,
        description=row.description,
        category=row.category,  # type: ignore[arg-type]
        occurrences=row.occurrences,
        affected_okr_ids=list(row.affected_okr_ids or []),
        supersedes_id=row.supersedes_id,
        created_at=row.created_at,
    )
