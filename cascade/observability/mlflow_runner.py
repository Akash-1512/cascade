"""MLflow integration for the eval gate.

Each invocation of :func:`cascade.evals.gate.run_evals` runs inside an
:func:`mlflow_run` context. When ``mlflow_tracking_uri`` is configured,
the context starts an MLflow run, records the metrics and params, and
closes the run on exit. When unset, the context yields ``None`` and the
log functions are no-ops — same call shape, no conditional logic in
the eval gate.

Imports of ``mlflow`` are lazy so the test suite (and CI without an
MLflow server) doesn't have to install the package. Construction
failures degrade to no-op with a WARNING — eval gate runs must never
fail because the telemetry sink is down.
"""

from __future__ import annotations

import logging
from contextlib import contextmanager
from typing import TYPE_CHECKING, Any

from cascade.config import get_settings

if TYPE_CHECKING:
    from collections.abc import Iterator

logger = logging.getLogger(__name__)


@contextmanager
def mlflow_run(run_name: str, *, tags: dict[str, str] | None = None) -> Iterator[object | None]:
    """Yield an active MLflow run, or ``None`` when MLflow isn't configured.

    Args:
        run_name: Display name for the MLflow run UI.
        tags: Optional run tags. ``cascade.version`` and ``cascade.surface``
            are sensible additions; the eval gate adds them itself so most
            callers can leave this empty.

    Yields:
        The active ``mlflow.ActiveRun`` when MLflow is configured and the
        connection succeeded, otherwise None. Callers can use ``run`` for
        nested artifact logging or pass to other MLflow APIs; passing the
        ``None`` case to the log helpers in this module is safe.

    Even if MLflow is configured, a connection failure (server down, bad
    URI) yields ``None`` rather than raising. The eval gate must run.
    """
    settings = get_settings()
    if settings.mlflow_tracking_uri is None:
        yield None
        return

    try:
        import mlflow  # type: ignore[import-not-found]
    except ImportError:
        logger.warning(
            "MLFLOW_TRACKING_URI is set but the mlflow package is not installed. "
            "Install with: pip install 'cascade[observability]'"
        )
        yield None
        return

    try:
        mlflow.set_tracking_uri(settings.mlflow_tracking_uri)
        mlflow.set_experiment(settings.mlflow_experiment)
    except Exception:
        logger.exception("Failed to configure MLflow tracking; continuing without telemetry")
        yield None
        return

    try:
        with mlflow.start_run(run_name=run_name, tags=tags) as run:
            yield run
    except Exception:
        logger.exception("Failed to start MLflow run %s; continuing without telemetry", run_name)
        yield None


def log_metrics(metrics: dict[str, float]) -> None:
    """Log a flat dict of metrics to the active MLflow run, no-op if no run.

    Numeric values only. NaN and infinity are filtered (MLflow rejects
    them and the rejection would surface as a noisy WARNING per metric).
    """
    if not _has_active_run():
        return
    import mlflow  # type: ignore[import-not-found]

    sanitised = {
        k: float(v) for k, v in metrics.items() if isinstance(v, int | float) and _is_finite(v)
    }
    if sanitised:
        try:
            mlflow.log_metrics(sanitised)
        except Exception:
            logger.exception("Failed to log MLflow metrics")


def log_params(params: dict[str, Any]) -> None:
    """Log a flat dict of params to the active MLflow run, no-op if no run.

    Values are coerced to string because MLflow stores params as text.
    """
    if not _has_active_run():
        return
    import mlflow  # type: ignore[import-not-found]

    stringified = {k: str(v) for k, v in params.items()}
    try:
        mlflow.log_params(stringified)
    except Exception:
        logger.exception("Failed to log MLflow params")


def _has_active_run() -> bool:
    """True iff there's an active MLflow run we can write to."""
    try:
        import mlflow  # type: ignore[import-not-found]
    except ImportError:
        return False
    try:
        return mlflow.active_run() is not None
    except Exception:
        return False


def _is_finite(v: float) -> bool:
    """True for finite floats; False for NaN, +inf, -inf."""
    import math

    return not (math.isnan(v) or math.isinf(v))


__all__ = ["log_metrics", "log_params", "mlflow_run"]
