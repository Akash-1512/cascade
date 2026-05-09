"""Check-in routes."""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy import select

from cascade.api.auth import Principal, require_principal
from cascade.api.dependencies import SessionDep
from cascade.api.schemas import CheckInCreateRequest, CheckInResponse
from cascade.domain.enums import CheckInConfidence, KeyResultStatus
from cascade.storage.models import CheckInORM, KeyResultORM

router = APIRouter(prefix="/v1", tags=["checkins"])


# Map confidence levels to default statuses when the client doesn't pick one
# explicitly. Mirrors the rule in cascade.mcp.tools._resolve_status so the
# REST and MCP surfaces produce identical state shapes for the same input.
_DEFAULT_STATUS_BY_CONFIDENCE = {
    CheckInConfidence.HIGH: KeyResultStatus.ON_TRACK,
    CheckInConfidence.MEDIUM: KeyResultStatus.AT_RISK,
    CheckInConfidence.LOW: KeyResultStatus.OFF_TRACK,
}


@router.post(
    "/key-results/{key_result_id}/checkins",
    response_model=CheckInResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Log a CheckIn against a Key Result",
)
async def create_checkin_for_kr(
    key_result_id: UUID,
    body: CheckInCreateRequest,
    response: Response,
    session: SessionDep,
    principal: Annotated[Principal, Depends(require_principal)],
) -> CheckInResponse:
    """Persist a check-in for ``key_result_id``.

    Returns 201 with the canonical :class:`CheckInResponse`. The
    ``Location`` header points at the canonical (eventual) GET path —
    individual check-in fetch isn't implemented yet, so the link refers
    to the ORM-level resource.

    The persisted ``status`` is taken from ``body.new_status`` if set, or
    derived from ``body.confidence`` otherwise (high → on_track, medium →
    at_risk, low → off_track). This matches the MCP ``log_checkin`` tool.

    A 404 is returned if the Key Result doesn't exist.
    """
    # Confirm the KR exists. Treating a missing KR as 404 instead of an
    # opaque IntegrityError makes the failure mode much clearer.
    result = await session.execute(select(KeyResultORM).where(KeyResultORM.id == key_result_id))
    if result.scalar_one_or_none() is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Key Result {key_result_id} not found",
        )

    confidence_enum = CheckInConfidence(body.confidence)
    status_enum: KeyResultStatus = (
        KeyResultStatus(body.new_status)
        if body.new_status is not None
        else _DEFAULT_STATUS_BY_CONFIDENCE[confidence_enum]
    )

    author_id = _resolve_author_id(body.author_id, principal)

    check_in = CheckInORM(
        key_result_id=key_result_id,
        progress_value=body.progress_value,
        confidence=confidence_enum,
        status=status_enum,
        blockers=body.blockers,
        narrative=body.narrative,
        author_id=author_id,
    )
    session.add(check_in)
    await session.flush()
    await session.refresh(check_in)
    await session.commit()

    response.headers["Location"] = f"/v1/key-results/{key_result_id}/checkins/{check_in.id}"
    # SQLAlchemy + SQLite (test override) sometimes returns enum columns as raw
    # strings rather than the StrEnum member after refresh; handle both.
    confidence_value = (
        check_in.confidence.value
        if hasattr(check_in.confidence, "value")
        else str(check_in.confidence)
    )
    status_value = (
        check_in.status.value if hasattr(check_in.status, "value") else str(check_in.status)
    )
    return CheckInResponse(
        id=str(check_in.id),
        key_result_id=str(check_in.key_result_id),
        progress_value=check_in.progress_value,
        confidence=confidence_value,  # type: ignore[arg-type]
        status=status_value,  # type: ignore[arg-type]
        narrative=check_in.narrative,
        blockers=check_in.blockers,
        author_id=str(check_in.author_id),
        created_at=check_in.created_at,
    )


def _resolve_author_id(body_author_id: str | None, principal: Principal) -> UUID:
    """Pick the author_id to record on a CheckIn.

    Priority: explicit body field > principal's user_id. Same shape as the
    decisions endpoint's actor resolution — service accounts can record
    check-ins on behalf of a real user by passing the human's id in the
    body.
    """
    if body_author_id is not None:
        try:
            return UUID(body_author_id)
        except ValueError as exc:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=f"author_id is not a valid UUID: {body_author_id!r}",
            ) from exc
    return principal.user_id


__all__ = ["router"]
