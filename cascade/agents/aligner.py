"""Aligner agent — checks vertical and horizontal OKR alignment."""

from __future__ import annotations

import json
import logging
from typing import TYPE_CHECKING

from cascade.agents.contracts import AlignmentResult, ProposedObjective
from cascade.agents.llm import with_structured_output
from cascade.agents.prompts import render_prompt

if TYPE_CHECKING:
    from langchain_core.language_models import BaseChatModel

    from cascade.domain.okr import Objective

logger = logging.getLogger(__name__)


class AlignerError(Exception):
    """The Aligner failed to produce a valid alignment result."""


# Vertical-score floor for the ``aligned`` verdict; below this the verdict
# softens. Documented in the prompt and enforced here so the gate is deterministic.
VERTICAL_PASS_THRESHOLD = 0.7
VERTICAL_BLOCK_THRESHOLD = 0.4


async def check_alignment(
    *,
    proposal: ProposedObjective,
    parent_objective: Objective | None,
    peer_objectives: list[Objective],
    model: BaseChatModel,
) -> AlignmentResult:
    """Score vertical alignment and detect horizontal conflicts.

    Args:
        proposal: The drafted Objective under review.
        parent_objective: The proposal's parent OKR if any.
        peer_objectives: Other OKRs at the same team level for the same quarter.
        model: The chat model.

    Returns:
        An :class:`AlignmentResult` with ``vertical_score``, conflicts, verdict,
        and suggestions.

    Raises:
        AlignerError: if the model returns a payload that cannot be parsed.
    """
    prompt = render_prompt(
        "aligner",
        proposal=proposal,
        parent_objective=parent_objective,
        peer_objectives=peer_objectives,
    )

    try:
        structured_model = with_structured_output(model, AlignmentResult)
        result = await structured_model.ainvoke(prompt)
    except Exception as exc:
        logger.warning("structured_output failed, falling back to raw parse: %s", exc)
        raw = await model.ainvoke(prompt)
        result = _parse_alignment_from_raw(raw.content if hasattr(raw, "content") else raw)

    if not isinstance(result, AlignmentResult):
        raise AlignerError(f"Aligner returned unexpected type: {type(result).__name__}")

    return _normalise_verdict(result)


def _normalise_verdict(result: AlignmentResult) -> AlignmentResult:
    """Override the LLM's verdict if dimension scores or conflict severities disagree.

    Routing precedence:

    1. Any blocking conflict OR vertical_score < 0.4 → blocked
    2. Any warning conflict OR vertical_score < 0.7 → needs_review
    3. Otherwise → aligned
    """
    has_blocking = any(c.severity == "blocking" for c in result.conflicts)
    has_warning = any(c.severity == "warning" for c in result.conflicts)

    if has_blocking or result.vertical_score < VERTICAL_BLOCK_THRESHOLD:
        verdict = "blocked"
    elif has_warning or result.vertical_score < VERTICAL_PASS_THRESHOLD:
        verdict = "needs_review"
    else:
        verdict = "aligned"

    if verdict != result.verdict:
        return result.model_copy(update={"verdict": verdict})
    return result


def _parse_alignment_from_raw(content: str | object) -> AlignmentResult:
    if not isinstance(content, str):
        raise AlignerError(f"unexpected raw content type: {type(content).__name__}")

    text = content.strip()
    if text.startswith("```"):
        lines = text.splitlines()
        text = "\n".join(lines[1:-1] if lines[-1].startswith("```") else lines[1:])

    try:
        payload = json.loads(text)
    except json.JSONDecodeError as exc:
        raise AlignerError(f"Aligner output was not valid JSON: {exc}") from exc

    try:
        return AlignmentResult.model_validate(payload)
    except Exception as exc:
        raise AlignerError(f"Aligner output failed validation: {exc}") from exc


__all__ = [
    "VERTICAL_BLOCK_THRESHOLD",
    "VERTICAL_PASS_THRESHOLD",
    "AlignerError",
    "check_alignment",
]
