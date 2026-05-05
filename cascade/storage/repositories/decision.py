"""Repository for the :class:`Decision` aggregate.

Decisions are append-only — the only mutations are creation and link insertion. This
matches the auditing requirements documented in ADR-0002.
"""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from cascade.domain.decision import (
    Alternative,
    Decision,
    DecisionCreate,
    Evidence,
)
from cascade.storage.models import DecisionLinkORM, DecisionORM
from cascade.storage.repositories import (
    BaseRepository,
    NotFoundError,
    RepositoryError,
)


class DecisionRepository(BaseRepository[Decision]):
    """Persistence for :class:`Decision`."""

    async def create(self, payload: DecisionCreate, *, actor_id: UUID) -> Decision:
        """Persist a new decision."""
        orm = DecisionORM(
            event_type=payload.event_type,
            objective_id=payload.objective_id,
            key_result_id=payload.key_result_id,
            summary=payload.summary,
            alternatives=[alt.model_dump() for alt in payload.alternatives],
            chosen=payload.chosen,
            tradeoff=payload.tradeoff,
            evidence=[e.model_dump() for e in payload.evidence],
            actor_id=actor_id,
            transcript_ref=payload.transcript_ref,
        )
        self._session.add(orm)
        try:
            await self._session.flush()
        except IntegrityError as exc:
            await self._session.rollback()
            raise RepositoryError(f"failed to record decision: {exc.orig}") from exc
        await self._session.refresh(orm)
        return self._to_domain(orm)

    async def get(self, decision_id: UUID) -> Decision:
        """Fetch a decision by primary key."""
        orm = await self._session.get(DecisionORM, decision_id)
        if orm is None:
            raise NotFoundError("decision", decision_id)
        return self._to_domain(orm)

    async def list_for_objective(
        self,
        objective_id: UUID,
        *,
        limit: int = 100,
    ) -> list[Decision]:
        """All decisions for an Objective, newest first."""
        stmt = (
            select(DecisionORM)
            .where(DecisionORM.objective_id == objective_id)
            .order_by(DecisionORM.created_at.desc())
            .limit(limit)
        )
        result = await self._session.execute(stmt)
        return [self._to_domain(row) for row in result.scalars().all()]

    async def list_for_key_result(
        self,
        key_result_id: UUID,
        *,
        limit: int = 100,
    ) -> list[Decision]:
        """All decisions referencing a specific Key Result."""
        stmt = (
            select(DecisionORM)
            .where(DecisionORM.key_result_id == key_result_id)
            .order_by(DecisionORM.created_at.desc())
            .limit(limit)
        )
        result = await self._session.execute(stmt)
        return [self._to_domain(row) for row in result.scalars().all()]

    async def link(
        self,
        from_id: UUID,
        to_id: UUID,
        relation: str,
    ) -> None:
        """Link two decisions with a typed relation.

        Raises:
            ValueError: if the relation is not in the allowed set.
            RepositoryError: if either decision does not exist or the link
                would violate the no-self-link constraint.
        """
        if relation not in {"caused_by", "reverses", "reinforces"}:
            raise ValueError(f"invalid relation: {relation!r}")
        if from_id == to_id:
            raise ValueError("a decision cannot link to itself")

        link = DecisionLinkORM(from_id=from_id, to_id=to_id, relation=relation)
        self._session.add(link)
        try:
            await self._session.flush()
        except IntegrityError as exc:
            await self._session.rollback()
            raise RepositoryError(f"failed to link decisions: {exc.orig}") from exc

    @staticmethod
    def _to_domain(orm: DecisionORM) -> Decision:
        return Decision(
            id=orm.id,
            event_type=orm.event_type,
            objective_id=orm.objective_id,
            key_result_id=orm.key_result_id,
            summary=orm.summary,
            alternatives=[Alternative(**alt) for alt in orm.alternatives],
            chosen=orm.chosen,
            tradeoff=orm.tradeoff,
            evidence=[Evidence(**e) for e in orm.evidence],
            actor_id=orm.actor_id,
            transcript_ref=orm.transcript_ref,
            created_at=orm.created_at,
        )
