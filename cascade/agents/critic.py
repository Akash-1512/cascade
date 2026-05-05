"""Critic agent — evaluates a drafted OKR against four dimensions."""

from __future__ import annotations

import json
import logging
from typing import TYPE_CHECKING

from cascade.agents.contracts import CritiqueResult, ProposedObjective
from cascade.agents.llm import with_structured_output
from cascade.agents.prompts import render_prompt

if TYPE_CHECKING:
    from langchain_core.language_models import BaseChatModel

logger = logging.getLogger(__name__)


class CriticError(Exception):
    """The Critic failed to produce a valid critique."""


# Threshold below which the Critic's verdict triggers a Drafter loop.
PASS_THRESHOLD = 0.7


async def critique_proposal(
    *,
    proposal: ProposedObjective,
    model: BaseChatModel,
) -> CritiqueResult:
    """Score a proposed Objective against the four critique dimensions.

    The verdict returned by the model is normalised against ``PASS_THRESHOLD`` and
    the per-dimension scores. We do not trust the LLM to apply the threshold
    consistently — we let it pick a verdict but override to ``needs_revision`` if
    any dimension falls below the threshold and the model said ``pass``.

    Args:
        proposal: The drafted Objective to evaluate.
        model: The chat model to use.

    Returns:
        A :class:`CritiqueResult` with per-dimension scores, vague-phrase list,
        verdict, and concrete suggestions.

    Raises:
        CriticError: if the model returns a payload that cannot be parsed.
    """
    prompt = render_prompt("critic", proposal=proposal)

    try:
        structured_model = with_structured_output(model, CritiqueResult)
        result = await structured_model.ainvoke(prompt)
    except Exception as exc:
        logger.warning("structured_output failed, falling back to raw parse: %s", exc)
        raw = await model.ainvoke(prompt)
        result = _parse_critique_from_raw(raw.content if hasattr(raw, "content") else raw)

    if not isinstance(result, CritiqueResult):
        raise CriticError(f"Critic returned unexpected type: {type(result).__name__}")

    return _normalise_verdict(result)


def _normalise_verdict(critique: CritiqueResult) -> CritiqueResult:
    """Override the LLM's verdict if it disagrees with the dimension scores.

    If any dimension is below ``PASS_THRESHOLD`` and the LLM said ``pass``, we flip
    to ``needs_revision``. This makes the gate behaviour deterministic regardless of
    model variance.
    """
    dimensions = [
        critique.specificity,
        critique.measurability,
        critique.ambition,
        critique.structure,
    ]
    min_score = min(d.score for d in dimensions)

    if critique.verdict == "pass" and min_score < PASS_THRESHOLD:
        return critique.model_copy(update={"verdict": "needs_revision"})

    return critique


def _parse_critique_from_raw(content: str | object) -> CritiqueResult:
    """Coerce a raw model output into a :class:`CritiqueResult`."""
    if not isinstance(content, str):
        raise CriticError(f"unexpected raw content type: {type(content).__name__}")

    text = content.strip()
    if text.startswith("```"):
        lines = text.splitlines()
        text = "\n".join(lines[1:-1] if lines[-1].startswith("```") else lines[1:])

    try:
        payload = json.loads(text)
    except json.JSONDecodeError as exc:
        raise CriticError(f"Critic output was not valid JSON: {exc}") from exc

    try:
        return CritiqueResult.model_validate(payload)
    except Exception as exc:
        raise CriticError(f"Critic output failed validation: {exc}") from exc


__all__ = ["PASS_THRESHOLD", "CriticError", "critique_proposal"]
