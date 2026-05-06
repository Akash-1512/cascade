"""Context builder — dynamic task-aware prompt assembly.

Replaces the conventional pattern of dumping a static context file (a la
``CLAUDE.md``) with retrieval that's tailored to the agent and the task.

The Drafter on a fresh OKR sees different context than the Drafter revising the
same OKR three weeks later. The Reflector sees aggregated retrospective patterns
that the Drafter never needs. Every retrieval is filtered, scored, and budgeted
per agent — there is no monolithic context.

ADR-0002 motivates this: static context injection suffers from "lost in the
middle" effects where the model under-weights material between the start and end
of the prompt. Retrieval-augmented prompts of 600-800 tokens consistently
outperform 5,000-token static dumps.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING
from uuid import UUID

from cascade.memory.types import MemoryQuery, RetrievedChunk

if TYPE_CHECKING:
    from cascade.domain.decision import Decision
    from cascade.memory.types import Retriever
    from cascade.storage.repositories.decision import DecisionRepository

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class AssembledContext:
    """The output of a single context-building call.

    Carries both the human-readable rendered text (for prompt insertion) and the
    structured pieces (for traces and debugging). Agents inject ``rendered`` into
    their prompts; observability uses ``decisions`` and ``chunks`` to surface what
    the model saw.
    """

    rendered: str
    decisions: list[Decision]
    chunks: list[RetrievedChunk]
    token_estimate: int

    @property
    def is_empty(self) -> bool:
        return not self.decisions and not self.chunks


# Per-agent retrieval budgets, in chunks. These are deliberately small — the
# Drafter doesn't need ten chunks of past context, it needs the three most relevant.
_AGENT_BUDGETS: dict[str, int] = {
    "drafter": 3,
    "critic": 2,
    "aligner": 5,
    "checkin_coach": 4,
    "reflector": 8,
    "risk_sentinel": 4,
}

# Rough proxy for token count — 4 chars per token is the conventional estimate.
_CHARS_PER_TOKEN = 4


class ContextBuilder:
    """Assembles task-aware retrieval context for an agent invocation.

    Args:
        retriever: The :class:`Retriever` used for conversational memory lookup.
        decision_repository: The :class:`DecisionRepository` used for causal-memory
            lookup. Pass ``None`` to skip causal memory (e.g., during a draft of a
            brand-new OKR with no decision history yet).
    """

    def __init__(
        self,
        *,
        retriever: Retriever,
        decision_repository: DecisionRepository | None = None,
    ) -> None:
        self._retriever = retriever
        self._decisions = decision_repository

    async def build(
        self,
        *,
        agent: str,
        intent: str,
        okr_id: UUID | None = None,
        team_id: UUID | None = None,
        quarter: str | None = None,
    ) -> AssembledContext:
        """Build context for a single agent invocation.

        Args:
            agent: The calling agent's name, used to pick the retrieval budget.
            intent: The user's natural-language intent or the current task — used
                as the retrieval query.
            okr_id: Filter conversational memory and pull causal decisions for this
                specific OKR. ``None`` means "any" (used for cold drafts).
            team_id: Filter chunks to a team's scope.
            quarter: Filter chunks to a planning period.

        Returns:
            An :class:`AssembledContext` with the rendered prompt section and the
            structured pieces it was built from.
        """
        budget = _AGENT_BUDGETS.get(agent, 3)

        decisions: list[Decision] = []
        if self._decisions is not None and okr_id is not None:
            decisions = await self._decisions.list_for_objective(okr_id, limit=10)

        chunks = await self._retriever.search(
            MemoryQuery(
                query=intent,
                okr_id=okr_id,
                team_id=team_id,
                quarter=quarter,
                limit=budget,
            )
        )

        rendered = _render_context(decisions=decisions, chunks=chunks)
        token_estimate = len(rendered) // _CHARS_PER_TOKEN

        return AssembledContext(
            rendered=rendered,
            decisions=decisions,
            chunks=chunks,
            token_estimate=token_estimate,
        )


def _render_context(*, decisions: list[Decision], chunks: list[RetrievedChunk]) -> str:
    """Render decisions and chunks into a structured context block."""
    if not decisions and not chunks:
        return ""

    parts: list[str] = []

    if decisions:
        parts.append("## Decision history")
        parts.append("")
        for d in decisions:
            line = f"- {d.created_at:%Y-%m-%d} [{d.event_type.value}]: {d.summary}"
            if d.tradeoff:
                line += f" — tradeoff accepted: {d.tradeoff}"
            parts.append(line)
        parts.append("")

    if chunks:
        parts.append("## Related context from memory")
        parts.append("")
        for i, hit in enumerate(chunks, start=1):
            parts.append(f"### {i}. {hit.chunk.metadata.get('kind', 'note')}")
            parts.append(hit.chunk.text.strip())
            parts.append("")

    return "\n".join(parts).rstrip() + "\n"
