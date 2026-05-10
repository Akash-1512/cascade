"""LangChain callback handlers for tracing and cost tracking.

Two integrations, each opt-in via environment variables:

- **LangSmith** activates automatically when ``LANGSMITH_API_KEY`` is set
  and ``LANGSMITH_TRACING=true``. The langchain library handles the
  callback wiring under the hood; we just verify the env is sane and
  surface the project name. No explicit handler is returned for
  LangSmith — it works through env activation alone.
- **Langfuse** requires explicit construction. When
  ``LANGFUSE_PUBLIC_KEY`` and ``LANGFUSE_SECRET_KEY`` are set, we build
  a :class:`LangfuseCallbackHandler` and include it in the callbacks
  list returned to the model factory. Langfuse is preferred for cost
  tracking because of its first-class token-pricing model.

Both integrations are silent no-ops when their keys aren't set, so a
developer running tests or a fresh clone never has to think about
observability. ``observability_state()`` returns a small dict describing
which integrations are active for log lines on startup.
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from typing import TYPE_CHECKING

from cascade.config import get_settings

if TYPE_CHECKING:
    from langchain_core.callbacks import BaseCallbackHandler

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class ObservabilityState:
    """Snapshot of which observability integrations are active.

    Returned by :func:`observability_state` for startup log lines and
    health-check inspection. Each field is independently true/false —
    Langfuse can be on with LangSmith off and vice-versa.
    """

    langsmith_active: bool
    langsmith_project: str | None
    langfuse_active: bool
    mlflow_active: bool
    mlflow_uri: str | None

    def summary_line(self) -> str:
        """Render as a single human-readable status line for startup logs."""
        parts = []
        if self.langsmith_active:
            parts.append(f"LangSmith→{self.langsmith_project}")
        if self.langfuse_active:
            parts.append("Langfuse")
        if self.mlflow_active:
            parts.append(f"MLflow→{self.mlflow_uri}")
        if not parts:
            return "observability: none configured"
        return "observability: " + ", ".join(parts)


def observability_state() -> ObservabilityState:
    """Inspect settings + environment to determine which integrations are active.

    LangSmith activation requires both ``LANGSMITH_TRACING=true`` AND a
    ``LANGSMITH_API_KEY`` (env var or settings). Either alone produces no
    tracing — checking for both prevents misleading "active" status when
    only the flag is flipped.
    """
    settings = get_settings()

    # LangSmith: tracing must be enabled AND a key must be present.
    # The langchain library reads these env vars directly; we mirror the
    # same logic to give an accurate active/inactive answer.
    langsmith_key = settings.langsmith_api_key
    langsmith_env_key = os.environ.get("LANGSMITH_API_KEY") or os.environ.get("LANGCHAIN_API_KEY")
    langsmith_active = settings.langsmith_tracing and bool(langsmith_key or langsmith_env_key)
    langsmith_project = settings.langsmith_project if langsmith_active else None

    # Langfuse: both keys must be present. Public-only or secret-only is
    # always a misconfiguration; treating it as inactive avoids surprise
    # 401s on the first model call.
    langfuse_active = bool(settings.langfuse_public_key and settings.langfuse_secret_key)

    mlflow_active = settings.mlflow_tracking_uri is not None

    return ObservabilityState(
        langsmith_active=langsmith_active,
        langsmith_project=langsmith_project,
        langfuse_active=langfuse_active,
        mlflow_active=mlflow_active,
        mlflow_uri=settings.mlflow_tracking_uri,
    )


def build_callback_handlers() -> list[BaseCallbackHandler]:
    """Return the callback handlers to attach to a chat model.

    Returns an empty list when no integration is active — the model factory
    can pass the result directly to LangChain without conditional logic.

    LangSmith is NOT in the returned list because it activates via
    environment variables that LangChain reads itself — passing a
    LangSmith handler explicitly would double-trace each call.
    """
    handlers: list[BaseCallbackHandler] = []
    state = observability_state()

    if state.langfuse_active:
        handler = _build_langfuse_handler()
        if handler is not None:
            handlers.append(handler)

    return handlers


def _build_langfuse_handler() -> BaseCallbackHandler | None:
    """Construct a :class:`LangfuseCallbackHandler` from settings.

    Returns None on import failure (langfuse not installed) or construction
    failure (auth invalid, host unreachable on init). Failures are logged
    at WARNING — observability outages should never crash the host
    application.
    """
    settings = get_settings()
    try:
        from langfuse.langchain import CallbackHandler as LangfuseCallbackHandler
    except ImportError:
        logger.warning(
            "Langfuse keys are set but the langfuse package is not installed. "
            "Install with: pip install 'cascade[observability]'"
        )
        return None

    try:
        # langfuse reads keys from env; surface them via os.environ so the
        # constructor picks them up without us hard-coding the auth path.
        public_key = settings.langfuse_public_key
        secret_key = settings.langfuse_secret_key
        if public_key is not None:
            os.environ.setdefault("LANGFUSE_PUBLIC_KEY", public_key.get_secret_value())
        if secret_key is not None:
            os.environ.setdefault("LANGFUSE_SECRET_KEY", secret_key.get_secret_value())
        os.environ.setdefault("LANGFUSE_HOST", settings.langfuse_host)
        return LangfuseCallbackHandler()
    except Exception:
        logger.exception(
            "Failed to construct Langfuse callback handler; continuing without Langfuse tracing"
        )
        return None


__all__ = [
    "ObservabilityState",
    "build_callback_handlers",
    "observability_state",
]
