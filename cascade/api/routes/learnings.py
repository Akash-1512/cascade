"""Organizational learning routes."""

from __future__ import annotations

from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, Query

from cascade.api.auth import Principal, require_principal
from cascade.api.dependencies import SessionDep
from cascade.api.schemas import LearningListResponse, LearningResponse
from cascade.domain.organizational_learning import OrganizationalLearning
from cascade.storage.repositories.organizational_learning import (
    OrganizationalLearningRepository,
)

router = APIRouter(prefix="/v1", tags=["learnings"])


@router.get(
    "/teams/{team_id}/learnings",
    response_model=LearningListResponse,
    summary="List organizational learnings for a team",
)
async def list_team_learnings(
    team_id: UUID,
    session: SessionDep,
    principal: Annotated[Principal, Depends(require_principal)],
    quarter: Annotated[
        str | None,
        Query(pattern=r"^\d{4}Q[1-4]$", description="Filter by quarter"),
    ] = None,
    category: Annotated[
        Literal["execution", "planning", "alignment", "estimation", "external", "process"] | None,
        Query(description="Filter by theme category"),
    ] = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 100,
) -> LearningListResponse:
    """Return organizational learning themes for a team, newest first.

    Filter by quarter to see what was learned in a specific period, or by
    category to see all 'estimation' or 'process' themes accumulated over
    time.
    """
    repo = OrganizationalLearningRepository(session)
    learnings = await repo.list_for_team(team_id, quarter=quarter, category=category, limit=limit)
    items = [_to_response(learning) for learning in learnings]
    return LearningListResponse(items=items, count=len(items))


def _to_response(learning: OrganizationalLearning) -> LearningResponse:
    return LearningResponse(
        id=str(learning.id),
        team_id=str(learning.team_id),
        quarter=learning.quarter,
        title=learning.title,
        description=learning.description,
        category=learning.category,
        occurrences=learning.occurrences,
        affected_okr_ids=list(learning.affected_okr_ids),
        supersedes_id=str(learning.supersedes_id) if learning.supersedes_id else None,
        created_at=learning.created_at,
    )


__all__ = ["router"]
