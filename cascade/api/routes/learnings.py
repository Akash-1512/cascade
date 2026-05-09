"""Organizational learning routes."""

from __future__ import annotations

from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status

from cascade.api.auth import Principal, require_principal
from cascade.api.dependencies import SessionDep
from cascade.api.schemas import (
    LearningCreateRequest,
    LearningListResponse,
    LearningResponse,
)
from cascade.domain.organizational_learning import (
    OrganizationalLearning,
    OrganizationalLearningCreate,
)
from cascade.storage.repositories import NotFoundError
from cascade.storage.repositories.organizational_learning import (
    OrganizationalLearningRepository,
)
from cascade.storage.repositories.team import TeamRepository

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


@router.post(
    "/teams/{team_id}/learnings",
    response_model=LearningResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Record an organizational learning for a team",
)
async def create_team_learning(
    team_id: UUID,
    body: LearningCreateRequest,
    response: Response,
    session: SessionDep,
    principal: Annotated[Principal, Depends(require_principal)],
) -> LearningResponse:
    """Persist a new organizational learning theme for ``team_id``.

    Returns 201 with the canonical :class:`LearningResponse`. The
    ``Location`` header points at the team's learnings list (no per-learning
    GET endpoint exists yet — paginate the list to find the new id).

    A 404 is returned if the team doesn't exist. Validation errors map to
    422 via FastAPI's default handling.
    """
    # Verify the team exists before committing — turns the foreign-key
    # violation into a 404 with an actionable message.
    team_repo = TeamRepository(session)
    try:
        await team_repo.get(team_id)
    except NotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Team {team_id} not found",
        ) from exc

    repo = OrganizationalLearningRepository(session)
    supersedes_uuid: UUID | None = None
    if body.supersedes_id is not None:
        try:
            supersedes_uuid = UUID(body.supersedes_id)
        except ValueError as exc:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=f"supersedes_id is not a valid UUID: {body.supersedes_id!r}",
            ) from exc

    learning = await repo.create(
        OrganizationalLearningCreate(
            team_id=team_id,
            quarter=body.quarter,
            title=body.title,
            description=body.description,
            category=body.category,
            occurrences=body.occurrences,
            affected_okr_ids=body.affected_okr_ids,
            supersedes_id=supersedes_uuid,
        )
    )
    response.headers["Location"] = f"/v1/teams/{team_id}/learnings"
    return _to_response(learning)


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
