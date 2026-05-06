"""Risk Sentinel agent — predicts at-risk OKRs and recommends interventions."""

from __future__ import annotations

import json
import logging
from typing import TYPE_CHECKING

from cascade.agents.contracts import RiskAssessment
from cascade.agents.llm import with_structured_output
from cascade.agents.prompts import render_prompt

if TYPE_CHECKING:
    from langchain_core.language_models import BaseChatModel

    from cascade.domain.checkin import CheckIn
    from cascade.domain.okr import Objective

logger = logging.getLogger(__name__)


class RiskError(Exception):
    """The Risk Sentinel failed to produce a valid assessment."""


# Threshold above which intervention is recommended. Stalled velocity overrides
# this regardless of score.
INTERVENTION_THRESHOLD = 0.5


async def assess_risk(
    *,
    okr: Objective,
    check_ins: list[CheckIn],
    weeks_elapsed: int,
    model: BaseChatModel,
) -> RiskAssessment:
    """Predict at-risk-ness for an OKR and recommend interventions.

    Args:
        okr: The Objective being assessed.
        check_ins: Recent check-ins in reverse chronological order. Pass an
            empty list for OKRs with no check-ins yet — the agent then bases
            risk on elapsed time and current progress.
        weeks_elapsed: How many weeks into the 13-week quarter we are.
        model: The chat model.

    Returns:
        A :class:`RiskAssessment` with risk score, velocity, factors, and
        recommended interventions. ``requires_intervention`` is normalised here:
        true when score > 0.5 OR velocity == 'stalled'.

    Raises:
        RiskError: if the model output cannot be parsed.
    """
    prompt = render_prompt(
        "risk_sentinel",
        okr=okr,
        check_ins=check_ins,
        weeks_elapsed=weeks_elapsed,
    )

    try:
        structured_model = with_structured_output(model, RiskAssessment)
        result = await structured_model.ainvoke(prompt)
    except Exception as exc:
        logger.warning("structured_output failed, falling back to raw parse: %s", exc)
        raw = await model.ainvoke(prompt)
        result = _parse_risk_from_raw(raw.content if hasattr(raw, "content") else raw)

    if not isinstance(result, RiskAssessment):
        raise RiskError(f"Risk Sentinel returned unexpected type: {type(result).__name__}")

    return _normalise_intervention_flag(result)


def _normalise_intervention_flag(result: RiskAssessment) -> RiskAssessment:
    """Force ``requires_intervention`` based on score and velocity, not the LLM's judgement."""
    should_intervene = (
        result.risk_score > INTERVENTION_THRESHOLD or result.velocity_assessment == "stalled"
    )
    if should_intervene != result.requires_intervention:
        return result.model_copy(update={"requires_intervention": should_intervene})
    return result


def _parse_risk_from_raw(content: str | object) -> RiskAssessment:
    if not isinstance(content, str):
        raise RiskError(f"unexpected raw content type: {type(content).__name__}")

    text = content.strip()
    if text.startswith("```"):
        lines = text.splitlines()
        text = "\n".join(lines[1:-1] if lines[-1].startswith("```") else lines[1:])

    try:
        payload = json.loads(text)
    except json.JSONDecodeError as exc:
        raise RiskError(f"Risk output was not valid JSON: {exc}") from exc

    try:
        return RiskAssessment.model_validate(payload)
    except Exception as exc:
        raise RiskError(f"Risk output failed validation: {exc}") from exc


__all__ = ["INTERVENTION_THRESHOLD", "RiskError", "assess_risk"]
