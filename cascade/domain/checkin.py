"""Check-in domain model.

A check-in is a periodic update against a Key Result — typically weekly or biweekly.
It captures the new measured value, the author's confidence, any blockers, and a
narrative the Coach agent uses for context in subsequent conversations.
"""

from __future__ import annotations

from datetime import datetime
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field

from cascade.domain.enums import CheckInConfidence, KeyResultStatus


class CheckIn(BaseModel):
    """A point-in-time progress update on a Key Result.

    Check-ins are append-only — corrections are made by adding a new check-in, not
    by editing an old one. This preserves the historical trajectory the Risk
    Sentinel uses for velocity prediction.
    """

    model_config = ConfigDict(extra="forbid")

    id: UUID = Field(default_factory=uuid4)
    key_result_id: UUID
    progress_value: float
    confidence: CheckInConfidence
    status: KeyResultStatus
    blockers: str | None = Field(default=None, max_length=2000)
    narrative: str = Field(min_length=1, max_length=4000)
    author_id: UUID
    created_at: datetime


class CheckInCreate(BaseModel):
    """Payload for posting a new check-in.

    The ``status`` field is optional on input — if omitted, it is derived from the
    ``confidence`` and the relative position of ``progress_value`` against target.
    """

    model_config = ConfigDict(extra="forbid")

    key_result_id: UUID
    progress_value: float
    confidence: CheckInConfidence
    status: KeyResultStatus | None = None
    blockers: str | None = Field(default=None, max_length=2000)
    narrative: str = Field(min_length=1, max_length=4000)
