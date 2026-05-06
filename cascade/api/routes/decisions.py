"""Decision routes — the causal trail."""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query

from cascade.api.auth import Principal, require_principal
from cascade.api.dependencies import SessionDep
from cascade.api.schemas import DecisionListResponse, DecisionResponse
from cascade.domain.decision import Decision
from cascade.storage.repositories.decision import DecisionRepository

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
