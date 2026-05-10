"""Observability for cascade: tracing, cost tracking, and eval telemetry.

Three integrations, each opt-in via environment variables:

- **LangSmith** for trace exploration. Activates automatically when
  ``LANGSMITH_API_KEY`` is set and ``LANGSMITH_TRACING=true``.
- **Langfuse** for trace exploration plus cost tracking. Activates when
  both ``LANGFUSE_PUBLIC_KEY`` and ``LANGFUSE_SECRET_KEY`` are set.
- **MLflow** for eval-run experiment tracking. Activates when
  ``MLFLOW_TRACKING_URI`` is set.

When none are configured, the module is a complete no-op — every public
function returns the appropriate empty value or yields ``None``. Callers
can wire instrumentation unconditionally without per-environment guards.

Construction failures (missing optional package, bad credentials,
unreachable server) all degrade to no-op with a WARNING log line.
Observability outages must not crash the host application.

See ``docs/runbooks/observability.md`` for setup instructions.
"""

from cascade.observability.handlers import (
    ObservabilityState,
    build_callback_handlers,
    observability_state,
)
from cascade.observability.mlflow_runner import log_metrics, log_params, mlflow_run

__all__ = [
    "ObservabilityState",
    "build_callback_handlers",
    "log_metrics",
    "log_params",
    "mlflow_run",
    "observability_state",
]
