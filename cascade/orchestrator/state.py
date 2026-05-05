"""Shared state for the LangGraph agent graph.

The state is the only thing agents communicate through. Each agent reads what it
needs and writes only its scoped fields — there are no side channels, no global
caches, no module-level state that leaks between runs.
"""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from cascade.agents.contracts import (
    CritiqueResult,
    DraftIteration,
    HumanInterrupt,
    ProposedObjective,
)
from cascade.domain.okr import Objective


def _replace(_existing: object, new: object) -> object:
    """Reducer that simply replaces the prior value."""
    return new


def _append(existing: list[object] | None, new: list[object]) -> list[object]:
    """Reducer that appends to a list; ``None`` initialises to empty."""
    return [*(existing or []), *new]


class OKRState(BaseModel):
    """Shared state for a single drafting and critique run.

    LangGraph annotations on each field tell the framework how to merge concurrent
    updates — most fields use a replace-strategy because only one agent writes to
    them at a time. ``iterations`` uses an append reducer because each iteration
    adds an entry rather than overwriting.
    """

    model_config = ConfigDict(arbitrary_types_allowed=True, extra="forbid")

    # Inputs --------------------------------------------------------------
    intent: Annotated[str, _replace] = ""
    parent_objective: Annotated[Objective | None, _replace] = None
    actor_id: Annotated[UUID | None, _replace] = None
    trace_id: Annotated[str, _replace] = ""

    # Working state -------------------------------------------------------
    proposal: Annotated[ProposedObjective | None, _replace] = None
    critique: Annotated[CritiqueResult | None, _replace] = None
    iterations: Annotated[list[DraftIteration], _append] = Field(default_factory=list)

    # Routing -------------------------------------------------------------
    next_agent: Annotated[str | None, _replace] = None
    awaiting_human: Annotated[HumanInterrupt | None, _replace] = None

    @property
    def iteration_count(self) -> int:
        """How many times the Drafter has produced a proposal in this run."""
        return len(self.iterations)
