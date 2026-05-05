"""Repository for the :class:`Objective` aggregate.

The Objective aggregate root owns its Key Results — they are loaded together and
modified through this repository.
"""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import selectinload

from cascade.domain.enums import KeyResultStatus, ObjectiveStatus
from cascade.domain.okr import (
    KeyResult,
    KeyResultCreate,
    Objective,
    ObjectiveCreate,
    Quarter,
)
from cascade.storage.models import KeyResultORM, ObjectiveORM
from cascade.storage.repositories import BaseRepository, NotFoundError, RepositoryError


class ObjectiveRepository(BaseRepository[Objective]):
    """Persistence for :class:`Objective` and its Key Results."""

    async def create(self, payload: ObjectiveCreate, *, owner_id: UUID) -> Objective:
        """Persist a new Objective with its Key Results in a single transaction."""
        orm = ObjectiveORM(
            title=payload.title,
            description=payload.description,
            owner_id=owner_id,
            team_id=payload.team_id,
            parent_objective_id=payload.parent_objective_id,
            quarter_year=payload.quarter.year,
            quarter_q=payload.quarter.quarter,
            status=ObjectiveStatus.DRAFT,
            key_results=[
                KeyResultORM(
                    description=kr.description,
                    metric_type=kr.metric_type,
                    baseline_value=kr.baseline_value,
                    target_value=kr.target_value,
                    current_value=kr.current_value
                    if kr.current_value is not None
                    else kr.baseline_value,
                    unit=kr.unit,
                    weight=kr.weight,
                    status=KeyResultStatus.NOT_STARTED,
                    owner_id=owner_id,
                )
                for kr in payload.key_results
            ],
        )
        self._session.add(orm)
        try:
            await self._session.flush()
        except IntegrityError as exc:
            await self._session.rollback()
            raise RepositoryError(f"failed to create objective: {exc.orig}") from exc
        await self._session.refresh(orm, attribute_names=["key_results"])
        return self._to_domain(orm)

    async def get(self, objective_id: UUID) -> Objective:
        """Fetch an Objective with its Key Results eagerly loaded."""
        result = await self._session.execute(
            select(ObjectiveORM)
            .options(selectinload(ObjectiveORM.key_results))
            .where(ObjectiveORM.id == objective_id)
        )
        orm = result.scalar_one_or_none()
        if orm is None:
            raise NotFoundError("objective", objective_id)
        return self._to_domain(orm)

    async def list_for_team(
        self,
        team_id: UUID,
        *,
        quarter: Quarter | None = None,
    ) -> list[Objective]:
        """All Objectives for a team, optionally filtered to a quarter."""
        stmt = (
            select(ObjectiveORM)
            .options(selectinload(ObjectiveORM.key_results))
            .where(ObjectiveORM.team_id == team_id)
            .order_by(
                ObjectiveORM.quarter_year.desc(),
                ObjectiveORM.quarter_q.desc(),
                ObjectiveORM.created_at.desc(),
            )
        )
        if quarter is not None:
            stmt = stmt.where(
                ObjectiveORM.quarter_year == quarter.year,
                ObjectiveORM.quarter_q == quarter.quarter,
            )
        result = await self._session.execute(stmt)
        return [self._to_domain(row) for row in result.scalars().all()]

    async def update_status(self, objective_id: UUID, status: ObjectiveStatus) -> Objective:
        """Transition the Objective to a new lifecycle state."""
        orm = await self._session.get(ObjectiveORM, objective_id)
        if orm is None:
            raise NotFoundError("objective", objective_id)
        orm.status = status
        orm.updated_at = datetime.now(tz=UTC)
        await self._session.flush()
        await self._session.refresh(orm, attribute_names=["key_results"])
        return self._to_domain(orm)

    async def add_key_result(
        self, objective_id: UUID, payload: KeyResultCreate, *, owner_id: UUID
    ) -> KeyResult:
        """Append a Key Result to an existing Objective."""
        objective_orm = await self._session.get(ObjectiveORM, objective_id)
        if objective_orm is None:
            raise NotFoundError("objective", objective_id)
        kr = KeyResultORM(
            objective_id=objective_id,
            description=payload.description,
            metric_type=payload.metric_type,
            baseline_value=payload.baseline_value,
            target_value=payload.target_value,
            current_value=payload.current_value
            if payload.current_value is not None
            else payload.baseline_value,
            unit=payload.unit,
            weight=payload.weight,
            status=KeyResultStatus.NOT_STARTED,
            owner_id=owner_id,
        )
        self._session.add(kr)
        await self._session.flush()
        await self._session.refresh(kr)
        return self._kr_to_domain(kr)

    @classmethod
    def _to_domain(cls, orm: ObjectiveORM) -> Objective:
        return Objective(
            id=orm.id,
            title=orm.title,
            description=orm.description,
            owner_id=orm.owner_id,
            team_id=orm.team_id,
            parent_objective_id=orm.parent_objective_id,
            quarter=Quarter(year=orm.quarter_year, quarter=orm.quarter_q),
            status=orm.status,
            key_results=[cls._kr_to_domain(kr) for kr in orm.key_results],
            created_at=orm.created_at,
            updated_at=orm.updated_at,
        )

    @staticmethod
    def _kr_to_domain(orm: KeyResultORM) -> KeyResult:
        return KeyResult(
            id=orm.id,
            objective_id=orm.objective_id,
            description=orm.description,
            metric_type=orm.metric_type,
            baseline_value=orm.baseline_value,
            target_value=orm.target_value,
            current_value=orm.current_value,
            unit=orm.unit,
            weight=orm.weight,
            status=orm.status,
            owner_id=orm.owner_id,
            created_at=orm.created_at,
            updated_at=orm.updated_at,
        )
