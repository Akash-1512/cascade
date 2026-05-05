"""Decision domain model — the causal memory primitive.

Every state-changing event on an OKR produces a Decision. The point of capturing
decisions structurally (rather than as free text in a chat log) is that the
*alternatives considered*, the *chosen option*, and the *tradeoff accepted* become
queryable, auditable, and citeable months later.

See ``docs/adr/0002-causal-memory-graph.md`` for the rationale.
"""

from __future__ import annotations

from datetime import datetime
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field

from cascade.domain.enums import DecisionEventType


class Alternative(BaseModel):
    """One option that was considered before the decision was made.

    Captured even when rejected — the *reason* for rejection is often more useful in
    retrospect than the alternatives that survived.
    """

    model_config = ConfigDict(extra="forbid")

    option: str = Field(min_length=1, max_length=500)
    reason_rejected: str = Field(min_length=1, max_length=1000)


class Evidence(BaseModel):
    """A citation supporting a decision.

    ``link`` is optional — sometimes evidence is a meeting outcome, a customer call,
    or a hallway conversation that doesn't have a URL.
    """

    model_config = ConfigDict(extra="forbid")

    source: str = Field(min_length=1, max_length=200)
    claim: str = Field(min_length=1, max_length=1000)
    link: str | None = Field(default=None, max_length=2000)


class Decision(BaseModel):
    """A captured causal event in the OKR lifecycle.

    Decisions reference either an Objective (``objective_id``) or a Key Result
    (``key_result_id``). The Coach and Reflector agents create most decisions; humans
    create some directly via the API when a change is initiated outside a
    conversation.
    """

    model_config = ConfigDict(extra="forbid")

    id: UUID = Field(default_factory=uuid4)
    event_type: DecisionEventType
    objective_id: UUID
    key_result_id: UUID | None = None
    summary: str = Field(min_length=10, max_length=500)
    alternatives: list[Alternative] = Field(default_factory=list, max_length=10)
    chosen: str = Field(min_length=1, max_length=500)
    tradeoff: str | None = Field(default=None, max_length=1000)
    evidence: list[Evidence] = Field(default_factory=list, max_length=10)
    actor_id: UUID
    transcript_ref: str | None = Field(
        default=None,
        max_length=200,
        description="Reference into ChromaDB ('collection:chunk_id') if this decision "
        "was extracted from a transcript.",
    )
    created_at: datetime


class DecisionCreate(BaseModel):
    """Payload for recording a decision via the API."""

    model_config = ConfigDict(extra="forbid")

    event_type: DecisionEventType
    objective_id: UUID
    key_result_id: UUID | None = None
    summary: str = Field(min_length=10, max_length=500)
    alternatives: list[Alternative] = Field(default_factory=list, max_length=10)
    chosen: str = Field(min_length=1, max_length=500)
    tradeoff: str | None = Field(default=None, max_length=1000)
    evidence: list[Evidence] = Field(default_factory=list, max_length=10)
    transcript_ref: str | None = Field(default=None, max_length=200)
