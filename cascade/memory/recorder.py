"""Memory recorder — bridges agent runs to decisions and transcripts.

When the agent graph finishes, three things must be persisted in the right order:

1. The proposed Objective is committed via :class:`ObjectiveRepository`, producing
   a real ``Objective`` row with an ``id``.
2. A :class:`Decision` row is written referencing that ``Objective.id`` — this is
   the causal record. For revisions, alternatives carry the prior drafts and
   tradeoffs carry what the Drafter accepted in the final pass.
3. The full iteration transcript (each draft + critique pair) is chunked and
   stored in :class:`MemoryStore` with metadata pointing back at the decision.

Doing this correctly is the difference between cascade's pitch ("we remember why")
and yet-another-OKR-tool. Decisions without transcripts are facts without context.
Transcripts without decisions are noise.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING
from uuid import UUID

from cascade.agents.contracts import DraftIteration, ProposedObjective
from cascade.domain.decision import Alternative, DecisionCreate, Evidence
from cascade.domain.enums import DecisionEventType
from cascade.domain.okr import (
    KeyResultCreate,
    ObjectiveCreate,
    Quarter,
)
from cascade.memory.types import MemoryChunk

if TYPE_CHECKING:
    from cascade.domain.decision import Decision
    from cascade.domain.okr import Objective
    from cascade.memory.types import MemoryStore
    from cascade.storage.repositories.decision import DecisionRepository
    from cascade.storage.repositories.objective import ObjectiveRepository

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class CommitOutcome:
    """The artefacts produced when a passing draft is committed."""

    objective: Objective
    decision: Decision
    chunk_ids: list[str]


class MemoryRecorder:
    """Persists agent outputs across the three storage tiers.

    Args:
        objectives: Repository for the relational OKR tables.
        decisions: Repository for the decision graph.
        memory_store: Vector store for conversational chunks.
    """

    def __init__(
        self,
        *,
        objectives: ObjectiveRepository,
        decisions: DecisionRepository,
        memory_store: MemoryStore,
    ) -> None:
        self._objectives = objectives
        self._decisions = decisions
        self._store = memory_store

    async def commit_drafted_objective(
        self,
        *,
        proposal: ProposedObjective,
        iterations: list[DraftIteration],
        team_id: UUID,
        quarter: Quarter,
        actor_id: UUID,
        parent_objective_id: UUID | None = None,
    ) -> CommitOutcome:
        """Commit a passing draft and capture the causal trail.

        The order matters: Objective first (we need the ID), then Decision (which
        references the ID), then transcript chunks (which reference both).
        """
        objective = await self._objectives.create(
            ObjectiveCreate(
                title=proposal.title,
                description=proposal.description,
                team_id=team_id,
                parent_objective_id=parent_objective_id,
                quarter=quarter,
                key_results=[
                    KeyResultCreate(
                        description=kr.description,
                        metric_type=kr.metric_type,
                        baseline_value=kr.baseline_value,
                        target_value=kr.target_value,
                        current_value=kr.current_value,
                        unit=kr.unit,
                        weight=kr.weight,
                    )
                    for kr in proposal.key_results
                ],
            ),
            owner_id=actor_id,
        )

        decision = await self._decisions.create(
            _build_commit_decision(
                proposal=proposal,
                iterations=iterations,
                objective_id=objective.id,
            ),
            actor_id=actor_id,
        )

        chunks = _build_transcript_chunks(
            iterations=iterations,
            objective_id=objective.id,
            decision_id=decision.id,
            team_id=team_id,
            quarter=str(quarter),
        )
        await self._store.add(chunks)

        return CommitOutcome(
            objective=objective,
            decision=decision,
            chunk_ids=[c.id for c in chunks],
        )


def _build_commit_decision(
    *,
    proposal: ProposedObjective,
    iterations: list[DraftIteration],
    objective_id: UUID,
) -> DecisionCreate:
    """Construct the :class:`DecisionCreate` payload for a committed draft.

    Alternatives carry the previous drafts that the Critic flagged for revision.
    Tradeoff captures the most-recent revision rationale, if any. Evidence carries
    the per-dimension critique scores so future readers can reconstruct *why* the
    draft passed.
    """
    alternatives: list[Alternative] = []
    for iteration in iterations[:-1]:  # all but the final, passing iteration
        alternatives.append(
            Alternative(
                option=f"Earlier draft: '{iteration.proposal.title}'",
                reason_rejected=_summarise_critique(iteration),
            )
        )

    tradeoff: str | None = None
    if len(iterations) >= 2:
        last_revision = iterations[-2]
        if last_revision.critique.suggestions:
            tradeoff = (
                f"Final draft addresses prior suggestions: "
                f"{'; '.join(last_revision.critique.suggestions[:3])}"
            )

    final_critique = iterations[-1].critique if iterations else None
    evidence: list[Evidence] = []
    if final_critique is not None:
        evidence.append(
            Evidence(
                source="cascade Critic agent",
                claim=(
                    f"specificity {final_critique.specificity.score:.2f}, "
                    f"measurability {final_critique.measurability.score:.2f}, "
                    f"ambition {final_critique.ambition.score:.2f}, "
                    f"structure {final_critique.structure.score:.2f}"
                ),
            )
        )

    return DecisionCreate(
        event_type=DecisionEventType.OBJECTIVE_COMMIT,
        objective_id=objective_id,
        summary=f"Committed Objective: {proposal.title}",
        alternatives=alternatives,
        chosen=proposal.title,
        tradeoff=tradeoff,
        evidence=evidence,
    )


def _summarise_critique(iteration: DraftIteration) -> str:
    """One-line summary of why a draft iteration was revised."""
    suggestions = iteration.critique.suggestions
    if suggestions:
        return f"Revised after Critic suggested: {suggestions[0]}"
    return f"Revised after Critic verdict: {iteration.critique.verdict}"


def _build_transcript_chunks(
    *,
    iterations: list[DraftIteration],
    objective_id: UUID,
    decision_id: UUID,
    team_id: UUID,
    quarter: str,
) -> list[MemoryChunk]:
    """Build conversational-memory chunks from the drafting transcript."""
    chunks: list[MemoryChunk] = []
    for iteration in iterations:
        proposal_text = _render_proposal(iteration.proposal)
        critique_text = _render_critique(iteration)
        text = (
            f"# Drafting iteration {iteration.iteration}\n\n"
            f"## Proposed Objective\n\n{proposal_text}\n\n"
            f"## Critic verdict\n\n{critique_text}\n"
        )
        chunks.append(
            MemoryChunk(
                id=f"{decision_id}:iter:{iteration.iteration}",
                text=text,
                metadata={
                    "okr_id": str(objective_id),
                    "decision_id": str(decision_id),
                    "team_id": str(team_id),
                    "quarter": quarter,
                    "kind": "drafting",
                    "iteration": iteration.iteration,
                },
            )
        )
    return chunks


def _render_proposal(proposal: ProposedObjective) -> str:
    lines = [f"**{proposal.title}**"]
    if proposal.description:
        lines.append(proposal.description)
    lines.append("")
    lines.append("Key Results:")
    for kr in proposal.key_results:
        baseline = _fmt_number(kr.baseline_value)
        target = _fmt_number(kr.target_value)
        unit = f" {kr.unit}" if kr.unit else ""
        lines.append(f"- {kr.description} ({kr.metric_type.value}: {baseline} → {target}{unit})")
    return "\n".join(lines)


def _render_critique(iteration: DraftIteration) -> str:
    c = iteration.critique
    lines = [
        f"Verdict: **{c.verdict}** (overall {c.overall_score:.2f})",
        f"- specificity: {c.specificity.score:.2f} — {c.specificity.reasoning}",
        f"- measurability: {c.measurability.score:.2f} — {c.measurability.reasoning}",
        f"- ambition: {c.ambition.score:.2f} — {c.ambition.reasoning}",
        f"- structure: {c.structure.score:.2f} — {c.structure.reasoning}",
    ]
    if c.vague_phrases:
        lines.append(f"Vague phrases: {', '.join(repr(p) for p in c.vague_phrases)}")
    if c.suggestions:
        lines.append("Suggestions:")
        for s in c.suggestions:
            lines.append(f"  - {s}")
    return "\n".join(lines)


def _fmt_number(value: float) -> str:
    if value.is_integer():
        return str(int(value))
    return str(value)
