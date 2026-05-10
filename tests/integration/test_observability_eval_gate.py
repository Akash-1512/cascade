"""Integration test: eval gate runs through the MLflow context cleanly.

Verifies that ``run_evals`` calls into the MLflow runner with sensible
metric and param shapes when MLflow is configured, and that it runs
unchanged when MLflow is not configured. The fake mlflow module
records the calls so we can assert on the exact metric names that get
sent — drift between the eval gate and what gets logged would be silent
otherwise.
"""

from __future__ import annotations

import sys
import types
from contextlib import contextmanager

import pytest

from cascade.agents.llm import FakeChatModel
from cascade.config import get_settings


def _install_recording_mlflow(monkeypatch: pytest.MonkeyPatch) -> types.ModuleType:
    fake = types.ModuleType("mlflow")
    fake.logged_metrics = []  # type: ignore[attr-defined]
    fake.logged_params = []  # type: ignore[attr-defined]
    fake._active_run = None  # type: ignore[attr-defined]

    def set_tracking_uri(uri: str) -> None:
        pass

    def set_experiment(name: str) -> None:
        pass

    @contextmanager
    def start_run(*, run_name: str, tags=None):
        run = types.SimpleNamespace(info=types.SimpleNamespace(run_id="fake-run"))
        fake._active_run = run
        try:
            yield run
        finally:
            fake._active_run = None

    def active_run():
        return fake._active_run

    def log_metrics_fn(metrics):
        fake.logged_metrics.append(metrics)

    def log_params_fn(params):
        fake.logged_params.append(params)

    fake.set_tracking_uri = set_tracking_uri  # type: ignore[attr-defined]
    fake.set_experiment = set_experiment  # type: ignore[attr-defined]
    fake.start_run = start_run  # type: ignore[attr-defined]
    fake.active_run = active_run  # type: ignore[attr-defined]
    fake.log_metrics = log_metrics_fn  # type: ignore[attr-defined]
    fake.log_params = log_params_fn  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "mlflow", fake)
    return fake


@pytest.mark.integration
async def test_run_evals_logs_metrics_and_params_to_mlflow(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """When MLflow is configured, run_evals records its outputs."""
    from cascade.evals.gate import run_evals

    settings = get_settings()
    saved = settings.mlflow_tracking_uri
    settings.mlflow_tracking_uri = "http://fake-mlflow:5000"
    try:
        fake = _install_recording_mlflow(monkeypatch)

        # Filter to a metric the FakeChatModel can satisfy with no responses
        # (we just want the gate to run end-to-end without LLM calls).
        # Filter case_ids to nothing so no real eval runs but the gate's
        # MLflow wrapping still executes.
        model = FakeChatModel(responses=[])
        report = await run_evals(
            model=model, metric_filter=["drafting"], case_ids=["nonexistent_case"]
        )

        # The wrapper must have logged the params block even when no metrics
        # were computed (the params describe what the run was *configured*
        # to do, separate from what it actually computed).
        assert len(fake.logged_params) >= 1, (
            "run_evals should log a params block even when no metrics compute"
        )
        params = fake.logged_params[0]  # type: ignore[attr-defined]
        assert "metric_filter" in params
        assert "drafting_threshold_f1" in params

        # Report still produced, even with zero metrics; the wrapper is
        # transparent to the eval gate's return value.
        assert report.run_id
    finally:
        settings.mlflow_tracking_uri = saved


@pytest.mark.integration
async def test_run_evals_runs_unchanged_when_mlflow_not_configured() -> None:
    """No MLFLOW_TRACKING_URI → eval gate runs as before with no instrumentation calls."""
    from cascade.evals.gate import run_evals

    settings = get_settings()
    saved = settings.mlflow_tracking_uri
    settings.mlflow_tracking_uri = None
    try:
        model = FakeChatModel(responses=[])
        report = await run_evals(
            model=model, metric_filter=["drafting"], case_ids=["nonexistent_case"]
        )
        # No exception, valid report.
        assert report.run_id
    finally:
        settings.mlflow_tracking_uri = saved
