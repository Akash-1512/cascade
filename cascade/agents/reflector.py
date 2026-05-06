"""Reflector agent — quarterly retrospective; extracts learning patterns."""

from __future__ import annotations

import json
import logging
from collections import defaultdict
from typing import TYPE_CHECKING

from cascade.agents.contracts import ReflectionResult
from cascade.agents.llm import with_structured_output
from cascade.agents.prompts import render_prompt

if TYPE_CHECKING:
    from langchain_core.language_models import BaseChatModel

    from cascade.domain.checkin import CheckIn
    from cascade.domain.decision import Decision
    from cascade.domain.okr import Objective

logger = logging.getLogger(__name__)


class ReflectorError(Exception):
    """The Reflector failed to produce a valid retrospective."""


async def reflect_on_quarter(
    *,
    quarter: str,
    okrs: list[Objective],
    check_ins: list[CheckIn],
    decisions: list[Decision],
    model: BaseChatModel,
) -> ReflectionResult:
    """Run a quarterly retrospective over the given OKRs and history.

    The Reflector is intentionally given unfiltered material — it's the agent
    whose job is to find the patterns. We don't pre-cluster or pre-filter;
    we just hand it the structured artefacts.

    Args:
        quarter: The planning period, e.g. ``"2026Q2"``.
        okrs: All OKRs that ran this quarter.
        check_ins: All check-ins across those OKRs.
        decisions: All decisions captured against those OKRs.
        model: The chat model.

    Returns:
        A :class:`ReflectionResult` with summary, themes, wins, losses, and
        recommendations.

    Raises:
        ReflectorError: if the model output cannot be parsed.
    """
    if not okrs:
        raise ReflectorError("Reflector requires at least one OKR")

    # Group check-ins and decisions by OKR id (as strings, since the template
    # iterates them through Jinja's string-keyed dict access).
    checkins_by_okr: dict[str, list[CheckIn]] = defaultdict(list)
    for c in check_ins:
        # CheckIn references KRs, which in turn belong to objectives. We surface
        # them under the parent OKR for the retrospective.
        owning_okr = _find_owning_okr(c, okrs)
        if owning_okr is not None:
            checkins_by_okr[str(owning_okr.id)].append(c)

    decisions_by_okr: dict[str, list[Decision]] = defaultdict(list)
    for d in decisions:
        decisions_by_okr[str(d.objective_id)].append(d)

    prompt = render_prompt(
        "reflector",
        quarter=quarter,
        okrs=okrs,
        checkins_by_okr=dict(checkins_by_okr),
        decisions_by_okr=dict(decisions_by_okr),
    )

    try:
        structured_model = with_structured_output(model, ReflectionResult)
        result = await structured_model.ainvoke(prompt)
    except Exception as exc:
        logger.warning("structured_output failed, falling back to raw parse: %s", exc)
        raw = await model.ainvoke(prompt)
        result = _parse_reflection_from_raw(raw.content if hasattr(raw, "content") else raw)

    if not isinstance(result, ReflectionResult):
        raise ReflectorError(f"Reflector returned unexpected type: {type(result).__name__}")

    return result


def _find_owning_okr(check_in: CheckIn, okrs: list[Objective]) -> Objective | None:
    """Find the Objective whose KRs include this check-in's ``key_result_id``."""
    for okr in okrs:
        for kr in okr.key_results:
            if kr.id == check_in.key_result_id:
                return okr
    return None


def _parse_reflection_from_raw(content: str | object) -> ReflectionResult:
    if not isinstance(content, str):
        raise ReflectorError(f"unexpected raw content type: {type(content).__name__}")

    text = content.strip()
    if text.startswith("```"):
        lines = text.splitlines()
        text = "\n".join(lines[1:-1] if lines[-1].startswith("```") else lines[1:])

    try:
        payload = json.loads(text)
    except json.JSONDecodeError as exc:
        raise ReflectorError(f"Reflector output was not valid JSON: {exc}") from exc

    try:
        return ReflectionResult.model_validate(payload)
    except Exception as exc:
        raise ReflectorError(f"Reflector output failed validation: {exc}") from exc


__all__ = ["ReflectorError", "reflect_on_quarter"]
