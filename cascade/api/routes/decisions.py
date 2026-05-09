"""Decision routes — the causal trail."""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status

from cascade.api.auth import Principal, require_principal
from cascade.api.dependencies import SessionDep
from cascade.api.schemas import (
    DecisionCreateRequest,
    DecisionListResponse,
    DecisionResponse,
)
from cascade.domain.decision import Alternative, Decision, DecisionCreate, Evidence
from cascade.domain.enums import DecisionEventType
from cascade.storage.repositories import NotFoundError
from cascade.storage.repositories.decision import DecisionRepository
from cascade.storage.repositories.objective import ObjectiveRepository

router = APIRouter(prefix="/v1", tags=["decisions"])


@router.get(
    "/okrs/{objective_id}/decisions",
    response_model=DecisionListResponse,
    summary="Get the causal trail for an Objective",
)
async def list_decisions_for_okr(
    objective_id: UUID,
    session: SessionDep,
    principal: Annotated[Principal, Depends(require_principal)],
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
) -> DecisionListResponse:
    """Return the decision history for an Objective, newest first.

    Each decision carries the alternatives considered, the chosen option, and
    the tradeoff accepted — the *why* behind the OKR's evolution.
    """
    repo = DecisionRepository(session)
    decisions = await repo.list_for_objective(objective_id, limit=limit)
    items = [_to_response(d) for d in decisions]
    return DecisionListResponse(items=items, count=len(items))


@router.post(
    "/okrs/{objective_id}/decisions",
    response_model=DecisionResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Log a Decision against an Objective",
)
async def create_decision_for_okr(
    objective_id: UUID,
    body: DecisionCreateRequest,
    response: Response,
    session: SessionDep,
    principal: Annotated[Principal, Depends(require_principal)],
) -> DecisionResponse:
    """Append a Decision to ``objective_id``'s causal trail.

    ``actor_id`` defaults to the JWT principal's user_id; pass it
    explicitly in the body to override (useful in dev mode where the
    bearer token is the user_id, or when a service account logs decisions
    on behalf of a real user — pass the real user's id in the body).

    Returns 201 with the canonical :class:`DecisionResponse`. 404 if the
    Objective doesn't exist; 422 if any UUID field is malformed.
    """
    # Verify the OKR exists. The ORM cascade would otherwise turn this into
    # an opaque IntegrityError; the 404 is much more actionable for the
    # client.
    okr_repo = ObjectiveRepository(session)
    try:
        await okr_repo.get(objective_id)
    except NotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Objective {objective_id} not found",
        ) from exc

    actor_id = _resolve_actor_id(body.actor_id, principal)
    key_result_uuid = _parse_optional_uuid(body.key_result_id, "key_result_id")

    decision_repo = DecisionRepository(session)
    decision = await decision_repo.create(
        DecisionCreate(
            event_type=DecisionEventType(body.event_type),
            objective_id=objective_id,
            key_result_id=key_result_uuid,
            summary=body.summary,
            chosen=body.chosen,
            tradeoff=body.tradeoff,
            alternatives=[
                Alternative(option=alt.option, reason_rejected=alt.reason_rejected)
                for alt in body.alternatives
            ],
            evidence=[
                Evidence(source=ev.source, claim=ev.claim, link=ev.link) for ev in body.evidence
            ],
        ),
        actor_id=actor_id,
    )
    response.headers["Location"] = f"/v1/okrs/{objective_id}/decisions"
    return _to_response(decision)


def _resolve_actor_id(body_actor_id: str | None, principal: Principal) -> UUID:
    """Pick the actor_id to record on a Decision.

    Priority: explicit body field > principal's user_id. The body override
    exists for service accounts that log decisions on behalf of a real user
    (the human's id goes in the body, the service's identity is the
    principal). If neither is set, raise — every Decision must be
    attributable.
    """
    if body_actor_id is not None:
        try:
            return UUID(body_actor_id)
        except ValueError as exc:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=f"actor_id is not a valid UUID: {body_actor_id!r}",
            ) from exc
    return principal.user_id


def _parse_optional_uuid(value: str | None, field_name: str) -> UUID | None:
    if value is None:
        return None
    try:
        return UUID(value)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"{field_name} is not a valid UUID: {value!r}",
        ) from exc


def _to_response(d: Decision) -> DecisionResponse:
    return DecisionResponse(
        id=str(d.id),
        event_type=d.event_type.value,  # type: ignore[arg-type]
        objective_id=str(d.objective_id),
        key_result_id=str(d.key_result_id) if d.key_result_id else None,
        summary=d.summary,
        alternatives=[
            {"option": alt.option, "reason_rejected": alt.reason_rejected} for alt in d.alternatives
        ],
        chosen=d.chosen,
        tradeoff=d.tradeoff,
        evidence=[{"source": e.source, "claim": e.claim, "link": e.link or ""} for e in d.evidence],
        actor_id=str(d.actor_id),
        created_at=d.created_at,
    )


__all__ = ["router"]
