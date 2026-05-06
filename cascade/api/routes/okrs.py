"""OKR REST routes.

Read-only for now. Mutations (draft, commit, target change) flow through the
MCP server because that's where the agent loop lives — the REST API is a
read-side projection plus convenience accessors.
"""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status

from cascade.api.auth import Principal, require_principal
from cascade.api.dependencies import SessionDep
from cascade.api.schemas import (
    KeyResultResponse,
    ObjectiveResponse,
    ObjectiveSummaryResponse,
    OKRListResponse,
    ScoreBreakdownResponse,
)
from cascade.domain.okr import Objective, Quarter
from cascade.storage.repositories import NotFoundError
from cascade.storage.repositories.objective import ObjectiveRepository

router = APIRouter(prefix="/v1", tags=["okrs"])


@router.get(
    "/teams/{team_id}/okrs",
    response_model=OKRListResponse,
    summary="List OKRs for a team",
)
async def list_team_okrs(
    team_id: UUID,
    session: SessionDep,
    principal: Annotated[Principal, Depends(require_principal)],
    quarter: Annotated[
        str | None,
        Query(pattern=r"^\d{4}Q[1-4]$", description="Filter by quarter (e.g. 2026Q2)"),
    ] = None,
) -> OKRListResponse:
    """Return the OKRs owned by ``team_id``, newest first.

    Filter by quarter to narrow to one planning period.
    """
    quarter_obj = Quarter.from_string(quarter) if quarter else None
    repo = ObjectiveRepository(session)
    objectives = await repo.list_for_team(team_id, quarter=quarter_obj)
    items = [_to_summary(o) for o in objectives]
    return OKRListResponse(items=items, count=len(items))


@router.get(
    "/okrs/{objective_id}",
    response_model=ObjectiveResponse,
    summary="Get an Objective with its Key Results",
)
async def get_okr(
    objective_id: UUID,
    session: SessionDep,
    principal: Annotated[Principal, Depends(require_principal)],
) -> ObjectiveResponse:
    """Return a single Objective by id, including all of its Key Results.

    Returns 404 if no Objective exists at that id.
    """
    repo = ObjectiveRepository(session)
    try:
        objective = await repo.get(objective_id)
    except NotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    return _to_response(objective)


@router.get(
    "/okrs/{objective_id}/score",
    response_model=ScoreBreakdownResponse,
    summary="Compute the current score for an Objective",
)
async def get_okr_score(
    objective_id: UUID,
    session: SessionDep,
    principal: Annotated[Principal, Depends(require_principal)],
) -> ScoreBreakdownResponse:
    """Return the per-KR scoring breakdown for an Objective.

    Scores are derived from baseline, current, and target values — not stored
    independently.
    """
    repo = ObjectiveRepository(session)
    try:
        objective = await repo.get(objective_id)
    except NotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc

    return ScoreBreakdownResponse(
        objective_id=str(objective.id),
        overall_score=objective.score,
        key_result_scores=[
            {
                "id": str(kr.id),
                "description": kr.description,
                "score": kr.score,
            }
            for kr in objective.key_results
        ],
    )


def _to_summary(okr: Objective) -> ObjectiveSummaryResponse:
    return ObjectiveSummaryResponse(
        id=str(okr.id),
        title=okr.title,
        quarter=str(okr.quarter),
        status=okr.status.value,  # type: ignore[arg-type]
        score=okr.score,
    )


def _to_response(okr: Objective) -> ObjectiveResponse:
    return ObjectiveResponse(
        id=str(okr.id),
        title=okr.title,
        description=okr.description,
        quarter=str(okr.quarter),
        status=okr.status.value,  # type: ignore[arg-type]
        team_id=str(okr.team_id),
        owner_id=str(okr.owner_id),
        parent_objective_id=str(okr.parent_objective_id) if okr.parent_objective_id else None,
        score=okr.score,
        key_results=[
            KeyResultResponse(
                id=str(kr.id),
                description=kr.description,
                metric_type=kr.metric_type.value,  # type: ignore[arg-type]
                baseline_value=kr.baseline_value,
                target_value=kr.target_value,
                current_value=kr.current_value,
                unit=kr.unit,
                weight=kr.weight,
                status=kr.status.value,  # type: ignore[arg-type]
                score=kr.score,
            )
            for kr in okr.key_results
        ],
        created_at=okr.created_at,
        updated_at=okr.updated_at,
    )


__all__ = ["router"]
