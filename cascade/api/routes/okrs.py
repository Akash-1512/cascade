"""OKR REST routes.

Read endpoints plus a single creation endpoint for committing aligned
proposals into persistent state. Mid-life mutations (target changes,
descopes, replacements) flow through MCP because they involve the agent
loop; pure persistence of an aligned draft is fine over REST and lets a
CI pipeline create OKRs without spinning up the MCP server.
"""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status

from cascade.api.auth import Principal, require_principal
from cascade.api.dependencies import SessionDep
from cascade.api.schemas import (
    KeyResultResponse,
    ObjectiveCreateRequest,
    ObjectiveResponse,
    ObjectiveSummaryResponse,
    OKRListResponse,
    ScoreBreakdownResponse,
)
from cascade.domain.enums import MetricType
from cascade.domain.okr import KeyResultCreate, Objective, ObjectiveCreate, Quarter
from cascade.storage.repositories import NotFoundError
from cascade.storage.repositories.objective import ObjectiveRepository
from cascade.storage.repositories.team import TeamRepository

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


@router.post(
    "/teams/{team_id}/okrs",
    response_model=ObjectiveResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create an Objective from an aligned draft",
)
async def create_okr_for_team(
    team_id: UUID,
    body: ObjectiveCreateRequest,
    response: Response,
    session: SessionDep,
    principal: Annotated[Principal, Depends(require_principal)],
) -> ObjectiveResponse:
    """Persist a new Objective with its Key Results.

    Typical flow: a user drafts via ``start_okr_draft`` on the MCP server,
    optionally resolves any pause via ``resume_okr_draft``, then POSTs the
    aligned proposal here to commit it. The endpoint accepts a complete
    proposal — title, KRs, owner — because the alignment work happens in
    MCP.

    Returns 201 with the canonical :class:`ObjectiveResponse`. 404 if the
    team or parent OKR doesn't exist; 422 on UUID malformation or weight
    constraints (KR weights must each be in (0, 1]).
    """
    # Verify the team exists. A missing team would otherwise surface as an
    # IntegrityError on the foreign key — turn it into a 404 with the team
    # id named so the client knows what to fix.
    team_repo = TeamRepository(session)
    try:
        await team_repo.get(team_id)
    except NotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Team {team_id} not found",
        ) from exc

    # If a parent OKR was specified, confirm it exists. A dangling parent
    # reference is a much more common error than a deliberate no-op.
    okr_repo = ObjectiveRepository(session)
    parent_id: UUID | None = None
    if body.parent_objective_id is not None:
        try:
            parent_id = UUID(body.parent_objective_id)
        except ValueError as exc:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=f"parent_objective_id is not a valid UUID: {body.parent_objective_id!r}",
            ) from exc
        try:
            await okr_repo.get(parent_id)
        except NotFoundError as exc:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Parent Objective {parent_id} not found",
            ) from exc

    try:
        owner_uuid = UUID(body.owner_id)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"owner_id is not a valid UUID: {body.owner_id!r}",
        ) from exc

    payload = ObjectiveCreate(
        title=body.title,
        description=body.description,
        team_id=team_id,
        quarter=Quarter.from_string(body.quarter),
        parent_objective_id=parent_id,
        key_results=[
            KeyResultCreate(
                description=kr.description,
                metric_type=MetricType(kr.metric_type),
                baseline_value=kr.baseline_value,
                target_value=kr.target_value,
                current_value=kr.current_value
                if kr.current_value is not None
                else kr.baseline_value,
                unit=kr.unit,
                weight=kr.weight,
            )
            for kr in body.key_results
        ],
    )
    objective = await okr_repo.create(payload, owner_id=owner_uuid)
    response.headers["Location"] = f"/v1/okrs/{objective.id}"
    return _to_response(objective)


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
