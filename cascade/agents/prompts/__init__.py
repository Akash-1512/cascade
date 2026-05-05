"""Jinja2-based prompt template loader.

Templates live alongside this module as ``.j2`` files so they are version-controlled
in their own right and reviewable independently of the Python that consumes them.
The MLflow registry tracks versions of the rendered prompt; this loader is the only
code path that produces a prompt string.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Any

from jinja2 import Environment, FileSystemLoader, StrictUndefined, select_autoescape

_TEMPLATE_DIR = Path(__file__).parent


@lru_cache(maxsize=1)
def _env() -> Environment:
    env = Environment(
        loader=FileSystemLoader(_TEMPLATE_DIR),
        undefined=StrictUndefined,  # raise on missing variables — never silently emit empty
        autoescape=select_autoescape(disabled_extensions=("j2",)),
        trim_blocks=True,
        lstrip_blocks=True,
        keep_trailing_newline=True,
    )
    env.filters["nice_num"] = _nice_num
    return env


def _nice_num(value: float | int) -> str:
    """Render a number as an integer when it's whole, else as a float."""
    if isinstance(value, int):
        return str(value)
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value)


def render_prompt(name: str, **context: Any) -> str:
    """Render a prompt template by name.

    Args:
        name: The template filename without extension. ``"drafter"`` resolves to
            ``cascade/agents/prompts/drafter.j2``.
        **context: Variables passed to the template. Missing variables raise
            :class:`jinja2.UndefinedError` rather than rendering as empty.

    Returns:
        The rendered prompt as a string.

    Raises:
        TemplateNotFound: if no template with that name exists.
        UndefinedError: if a referenced variable is not in ``context``.
    """
    template = _env().get_template(f"{name}.j2")
    return template.render(**context)


def list_prompts() -> list[str]:
    """Return all available prompt names (filenames without extension)."""
    return sorted(p.stem for p in _TEMPLATE_DIR.glob("*.j2"))
