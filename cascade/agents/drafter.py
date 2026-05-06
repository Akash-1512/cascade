"""Drafter agent — converts strategic intent into a well-formed OKR proposal."""

from __future__ import annotations

import json
import logging
from typing import TYPE_CHECKING
from uuid import UUID

from cascade.agents.contracts import (
    DraftIteration,
    ProposedKeyResult,
    ProposedObjective,
)
from cascade.agents.llm import with_structured_output
from cascade.agents.prompts import render_prompt

if TYPE_CHECKING:
    from langchain_core.language_models import BaseChatModel

    from cascade.domain.okr import Objective
    from cascade.memory.context_builder import ContextBuilder

logger = logging.getLogger(__name__)


class DrafterError(Exception):
    """The Drafter failed to produce a valid proposal."""


async def draft_objective(
    *,
    intent: str,
    model: BaseChatModel,
    parent_objective: Objective | None = None,
    previous_attempts: list[DraftIteration] | None = None,
    context_builder: ContextBuilder | None = None,
    okr_id: UUID | None = None,
    team_id: UUID | None = None,
    quarter: str | None = None,
) -> ProposedObjective:
    """Draft a proposed Objective with Key Results.

    Args:
        intent: The user's free-text description of what they want to achieve.
        model: The chat model to use. Inject for testability.
        parent_objective: Optional parent OKR for alignment context.
        previous_attempts: Earlier (proposal, critique) pairs from this session, used
            to steer the Drafter away from previously-flagged issues.
        context_builder: Optional builder that pulls causal and conversational
            memory. When provided, the Drafter sees decisions and transcript
            chunks relevant to the current task.
        okr_id: Forwarded to the context builder. Used for revisions of an existing
            Objective — the Drafter sees the decisions on that exact OKR.
        team_id: Forwarded to the context builder for team-scoped retrieval.
        quarter: Forwarded to the context builder for quarter-scoped retrieval.

    Returns:
        A :class:`ProposedObjective` that has passed Pydantic validation. The Critic
        is responsible for evaluating quality — this function only enforces shape.

    Raises:
        DrafterError: if the model returns a payload that cannot be parsed into a
            :class:`ProposedObjective` after the wrapped retry attempts.
    """
    if not intent or not intent.strip():
        raise DrafterError("intent must not be empty")

    memory_context = ""
    if context_builder is not None:
        ctx = await context_builder.build(
            agent="drafter",
            intent=intent,
            okr_id=okr_id,
            team_id=team_id,
            quarter=quarter,
        )
        memory_context = ctx.rendered

    prompt = render_prompt(
        "drafter",
        intent=intent.strip(),
        parent_objective=parent_objective,
        previous_attempts=previous_attempts or [],
        memory_context=memory_context,
    )

    try:
        structured_model = with_structured_output(model, ProposedObjective)
        result = await structured_model.ainvoke(prompt)
    except Exception as exc:
        # If structured output isn't supported (older models, fakes) or fails to
        # parse, fall back to a raw call and parse the JSON ourselves.
        logger.warning("structured_output failed, falling back to raw parse: %s", exc)
        raw = await model.ainvoke(prompt)
        result = _parse_proposal_from_raw(raw.content if hasattr(raw, "content") else raw)

    if not isinstance(result, ProposedObjective):
        raise DrafterError(f"Drafter returned unexpected type: {type(result).__name__}")

    if not result.key_results:
        raise DrafterError("Drafter produced no Key Results")

    if len(result.key_results) > 5:
        # Trim rather than reject — a small overshoot is the model's enthusiasm,
        # not a structural failure. The Critic will catch the count problem
        # if it matters.
        logger.info("Trimming %d KRs to 5", len(result.key_results))
        result = result.model_copy(update={"key_results": result.key_results[:5]})

    return result


def _parse_proposal_from_raw(content: str | object) -> ProposedObjective:
    """Coerce a raw model output into a :class:`ProposedObjective`."""
    if not isinstance(content, str):
        raise DrafterError(f"unexpected raw content type: {type(content).__name__}")

    text = content.strip()

    # Strip markdown fences if the model added them despite our instructions
    if text.startswith("```"):
        lines = text.splitlines()
        text = "\n".join(lines[1:-1] if lines[-1].startswith("```") else lines[1:])

    try:
        payload = json.loads(text)
    except json.JSONDecodeError as exc:
        raise DrafterError(f"Drafter output was not valid JSON: {exc}") from exc

    # Coerce metric_type strings into enum-friendly form
    for kr in payload.get("key_results", []):
        mt = kr.get("metric_type")
        if isinstance(mt, str):
            kr["metric_type"] = mt.lower()

    try:
        return ProposedObjective.model_validate(payload)
    except Exception as exc:
        raise DrafterError(f"Drafter output failed validation: {exc}") from exc


__all__ = ["DrafterError", "ProposedKeyResult", "draft_objective"]
