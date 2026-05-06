"""Check-in Coach agent — runs progress conversations and captures decisions."""

from __future__ import annotations

import json
import logging
from typing import TYPE_CHECKING

from cascade.agents.contracts import CoachResponse
from cascade.agents.llm import with_structured_output
from cascade.agents.prompts import render_prompt

if TYPE_CHECKING:
    from langchain_core.language_models import BaseChatModel

    from cascade.domain.checkin import CheckIn
    from cascade.domain.okr import Objective
    from cascade.memory.context_builder import ContextBuilder

logger = logging.getLogger(__name__)


class CoachError(Exception):
    """The Coach failed to produce a valid response."""


async def run_checkin(
    *,
    objective: Objective,
    user_message: str,
    model: BaseChatModel,
    recent_check_ins: list[CheckIn] | None = None,
    context_builder: ContextBuilder | None = None,
) -> CoachResponse:
    """Run a single check-in conversation turn.

    Args:
        objective: The OKR being checked in on.
        user_message: The owner's free-text message.
        model: The chat model.
        recent_check_ins: Last few check-ins, newest first, used as conversation
            grounding so the Coach knows the trajectory.
        context_builder: Optional memory context. When provided, recent decisions
            on this OKR are surfaced — useful when a user says "as we discussed
            last quarter, ..." and the Coach needs the actual context.

    Returns:
        A :class:`CoachResponse` with proposed updates, a coaching message, and
        at most two follow-up questions.

    Raises:
        CoachError: if the model output cannot be parsed.
    """
    if not user_message or not user_message.strip():
        raise CoachError("user_message must not be empty")

    memory_context = ""
    if context_builder is not None:
        ctx = await context_builder.build(
            agent="checkin_coach",
            intent=user_message,
            okr_id=objective.id,
            team_id=objective.team_id,
            quarter=str(objective.quarter),
        )
        memory_context = ctx.rendered

    prompt = render_prompt(
        "checkin_coach",
        objective=objective,
        recent_check_ins=recent_check_ins or [],
        user_message=user_message.strip(),
        memory_context=memory_context,
    )

    try:
        structured_model = with_structured_output(model, CoachResponse)
        result = await structured_model.ainvoke(prompt)
    except Exception as exc:
        logger.warning("structured_output failed, falling back to raw parse: %s", exc)
        raw = await model.ainvoke(prompt)
        result = _parse_coach_from_raw(raw.content if hasattr(raw, "content") else raw)

    if not isinstance(result, CoachResponse):
        raise CoachError(f"Coach returned unexpected type: {type(result).__name__}")

    return _enforce_confirmation_flag(result)


def _enforce_confirmation_flag(response: CoachResponse) -> CoachResponse:
    """Force ``requires_confirmation`` on whenever a target value changes.

    The LLM occasionally forgets — we make it deterministic.
    """
    new_updates = []
    for update in response.updates:
        if update.new_target_value is not None and not update.requires_confirmation:
            new_updates.append(update.model_copy(update={"requires_confirmation": True}))
        else:
            new_updates.append(update)
    if new_updates != response.updates:
        return response.model_copy(update={"updates": new_updates})
    return response


def _parse_coach_from_raw(content: str | object) -> CoachResponse:
    if not isinstance(content, str):
        raise CoachError(f"unexpected raw content type: {type(content).__name__}")

    text = content.strip()
    if text.startswith("```"):
        lines = text.splitlines()
        text = "\n".join(lines[1:-1] if lines[-1].startswith("```") else lines[1:])

    try:
        payload = json.loads(text)
    except json.JSONDecodeError as exc:
        raise CoachError(f"Coach output was not valid JSON: {exc}") from exc

    try:
        return CoachResponse.model_validate(payload)
    except Exception as exc:
        raise CoachError(f"Coach output failed validation: {exc}") from exc


__all__ = ["CoachError", "run_checkin"]
