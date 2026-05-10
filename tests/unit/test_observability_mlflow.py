"""Tests for :mod:`cascade.observability.mlflow_runner`.

Pattern: monkey-patch settings + ``sys.modules['mlflow']`` to simulate
each combination (no URI, package missing, package present, run-start
failure). The fake mlflow module records its calls so tests can assert
on the side effects.
"""

from __future__ import annotations

import sys
import types
from contextlib import contextmanager

import pytest

from cascade.config import get_settings
from cascade.observability.mlflow_runner import log_metrics, log_params, mlflow_run


@pytest.fixture
def reset_mlflow_settings():
    settings = get_settings()
    saved = settings.mlflow_tracking_uri
    yield
    settings.mlflow_tracking_uri = saved


def _install_fake_mlflow(
    monkeypatch: pytest.MonkeyPatch,
    *,
    set_uri_raises: bool = False,
    start_run_raises: bool = False,
    log_metrics_raises: bool = False,
    log_params_raises: bool = False,
) -> types.ModuleType:
    """Install a controllable fake mlflow module and return it.

    The returned module records calls in ``calls`` and ``logged_metrics``,
    ``logged_params`` lists. Set the *_raises flags to exercise failure
    paths.
    """
    fake = types.ModuleType("mlflow")
    fake.calls = []  # type: ignore[attr-defined]
    fake.logged_metrics = []  # type: ignore[attr-defined]
    fake.logged_params = []  # type: ignore[attr-defined]
    fake._active_run = None  # type: ignore[attr-defined]

    def set_tracking_uri(uri: str) -> None:
        if set_uri_raises:
            raise ConnectionError("MLflow server unreachable")
        fake.calls.append(("set_tracking_uri", uri))

    def set_experiment(name: str) -> None:
        fake.calls.append(("set_experiment", name))

    @contextmanager
    def start_run(*, run_name: str, tags: dict[str, str] | None = None):
        if start_run_raises:
            raise RuntimeError("Run could not be started")
        run = types.SimpleNamespace(info=types.SimpleNamespace(run_id="fake-run-id"))
        fake._active_run = run
        fake.calls.append(("start_run", run_name, tags))
        try:
            yield run
        finally:
            fake._active_run = None

    def active_run() -> object | None:
        return fake._active_run

    def log_metrics_fn(metrics: dict[str, float]) -> None:
        if log_metrics_raises:
            raise ValueError("metrics rejected")
        fake.logged_metrics.append(metrics)

    def log_params_fn(params: dict[str, str]) -> None:
        if log_params_raises:
            raise ValueError("params rejected")
        fake.logged_params.append(params)

    fake.set_tracking_uri = set_tracking_uri  # type: ignore[attr-defined]
    fake.set_experiment = set_experiment  # type: ignore[attr-defined]
    fake.start_run = start_run  # type: ignore[attr-defined]
    fake.active_run = active_run  # type: ignore[attr-defined]
    fake.log_metrics = log_metrics_fn  # type: ignore[attr-defined]
    fake.log_params = log_params_fn  # type: ignore[attr-defined]

    monkeypatch.setitem(sys.modules, "mlflow", fake)
    return fake


# -- mlflow_run context -------------------------------------------------------


@pytest.mark.unit
def test_mlflow_run_yields_none_when_uri_not_configured(
    reset_mlflow_settings,
) -> None:
    settings = get_settings()
    settings.mlflow_tracking_uri = None
    with mlflow_run("test-run") as run:
        assert run is None


@pytest.mark.unit
def test_mlflow_run_yields_none_when_mlflow_package_missing(
    reset_mlflow_settings,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    settings = get_settings()
    settings.mlflow_tracking_uri = "http://mlflow:5000"
    # Ensure mlflow is not importable: replace with an import error sentinel.
    monkeypatch.setitem(sys.modules, "mlflow", None)

    with caplog.at_level("WARNING"), mlflow_run("test-run") as run:
        assert run is None


@pytest.mark.unit
def test_mlflow_run_starts_and_closes_run_when_configured(
    reset_mlflow_settings,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = get_settings()
    settings.mlflow_tracking_uri = "http://mlflow:5000"
    fake = _install_fake_mlflow(monkeypatch)

    with mlflow_run("test-run", tags={"cascade.version": "0.15.0"}) as run:
        assert run is not None
        assert fake._active_run is not None  # type: ignore[attr-defined]

    # Run is closed after the context exits.
    assert fake._active_run is None  # type: ignore[attr-defined]
    # set_tracking_uri and set_experiment were called.
    call_names = [c[0] for c in fake.calls]  # type: ignore[attr-defined]
    assert "set_tracking_uri" in call_names
    assert "set_experiment" in call_names
    assert "start_run" in call_names


@pytest.mark.unit
def test_mlflow_run_yields_none_when_set_tracking_uri_fails(
    reset_mlflow_settings,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Configuration failure must not crash the eval gate."""
    settings = get_settings()
    settings.mlflow_tracking_uri = "http://unreachable:5000"
    _install_fake_mlflow(monkeypatch, set_uri_raises=True)

    with caplog.at_level("ERROR"), mlflow_run("test-run") as run:
        assert run is None


@pytest.mark.unit
def test_mlflow_run_yields_none_when_start_run_fails(
    reset_mlflow_settings,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    settings = get_settings()
    settings.mlflow_tracking_uri = "http://mlflow:5000"
    _install_fake_mlflow(monkeypatch, start_run_raises=True)

    with caplog.at_level("ERROR"), mlflow_run("test-run") as run:
        assert run is None


# -- log_metrics --------------------------------------------------------------


@pytest.mark.unit
def test_log_metrics_is_noop_without_active_run(
    reset_mlflow_settings,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Calling log_metrics outside a run must not raise."""
    settings = get_settings()
    settings.mlflow_tracking_uri = "http://mlflow:5000"
    fake = _install_fake_mlflow(monkeypatch)

    # No active run yet.
    log_metrics({"f1": 0.92})
    assert fake.logged_metrics == []  # type: ignore[attr-defined]


@pytest.mark.unit
def test_log_metrics_writes_to_active_run(
    reset_mlflow_settings,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = get_settings()
    settings.mlflow_tracking_uri = "http://mlflow:5000"
    fake = _install_fake_mlflow(monkeypatch)

    with mlflow_run("test-run"):
        log_metrics({"f1": 0.92, "precision": 0.95})

    assert len(fake.logged_metrics) == 1  # type: ignore[attr-defined]
    assert fake.logged_metrics[0] == {"f1": 0.92, "precision": 0.95}  # type: ignore[attr-defined]


@pytest.mark.unit
def test_log_metrics_filters_nan_and_infinity(
    reset_mlflow_settings,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """NaN and infinity would be rejected by MLflow with a noisy warning per metric;
    filter them out at the boundary."""
    settings = get_settings()
    settings.mlflow_tracking_uri = "http://mlflow:5000"
    fake = _install_fake_mlflow(monkeypatch)

    with mlflow_run("test-run"):
        log_metrics(
            {
                "f1": 0.92,
                "broken_nan": float("nan"),
                "broken_inf": float("inf"),
                "broken_ninf": float("-inf"),
            }
        )

    assert fake.logged_metrics[0] == {"f1": 0.92}  # type: ignore[attr-defined]


@pytest.mark.unit
def test_log_metrics_swallows_mlflow_errors(
    reset_mlflow_settings,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """If MLflow rejects a metric mid-run, the eval gate must continue."""
    settings = get_settings()
    settings.mlflow_tracking_uri = "http://mlflow:5000"
    _install_fake_mlflow(monkeypatch, log_metrics_raises=True)

    with caplog.at_level("ERROR"), mlflow_run("test-run"):
        # Should not raise.
        log_metrics({"f1": 0.92})


# -- log_params ---------------------------------------------------------------


@pytest.mark.unit
def test_log_params_coerces_values_to_string(
    reset_mlflow_settings,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = get_settings()
    settings.mlflow_tracking_uri = "http://mlflow:5000"
    fake = _install_fake_mlflow(monkeypatch)

    with mlflow_run("test-run"):
        log_params({"threshold": 0.85, "filter": ["drafting", "retrieval"]})

    assert fake.logged_params[0] == {  # type: ignore[attr-defined]
        "threshold": "0.85",
        "filter": "['drafting', 'retrieval']",
    }


@pytest.mark.unit
def test_log_params_is_noop_without_active_run(
    reset_mlflow_settings,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = get_settings()
    settings.mlflow_tracking_uri = "http://mlflow:5000"
    fake = _install_fake_mlflow(monkeypatch)

    log_params({"foo": "bar"})  # outside any run
    assert fake.logged_params == []  # type: ignore[attr-defined]
