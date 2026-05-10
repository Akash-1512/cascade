"""Tests for :mod:`cascade.observability.handlers`.

Pattern: monkey-patch settings to flip integrations on/off, then inject
fake ``langfuse`` modules into ``sys.modules`` to verify construction
without needing the real package. The real package would also work but
the test would silently degrade to "import failed → no handler" without
catching the actual logic.
"""

from __future__ import annotations

import os
import sys
import types

import pytest
from pydantic import SecretStr

from cascade.config import get_settings
from cascade.observability.handlers import (
    ObservabilityState,
    build_callback_handlers,
    observability_state,
)


@pytest.fixture
def reset_settings_observability():
    """Save and restore observability-related settings around a test."""
    settings = get_settings()
    saved = {
        "langsmith_tracing": settings.langsmith_tracing,
        "langsmith_api_key": settings.langsmith_api_key,
        "langfuse_public_key": settings.langfuse_public_key,
        "langfuse_secret_key": settings.langfuse_secret_key,
        "mlflow_tracking_uri": settings.mlflow_tracking_uri,
    }
    saved_env = {
        k: os.environ.get(k)
        for k in (
            "LANGSMITH_API_KEY",
            "LANGCHAIN_API_KEY",
            "LANGFUSE_PUBLIC_KEY",
            "LANGFUSE_SECRET_KEY",
        )
    }
    yield
    for k, v in saved.items():
        setattr(settings, k, v)
    for k, v in saved_env.items():
        if v is None:
            os.environ.pop(k, None)
        else:
            os.environ[k] = v


# -- observability_state ------------------------------------------------------


@pytest.mark.unit
def test_state_reports_all_inactive_when_nothing_configured(
    reset_settings_observability,
) -> None:
    settings = get_settings()
    settings.langsmith_tracing = False
    settings.langsmith_api_key = None
    settings.langfuse_public_key = None
    settings.langfuse_secret_key = None
    settings.mlflow_tracking_uri = None
    for k in ("LANGSMITH_API_KEY", "LANGCHAIN_API_KEY"):
        os.environ.pop(k, None)

    state = observability_state()
    assert isinstance(state, ObservabilityState)
    assert state.langsmith_active is False
    assert state.langfuse_active is False
    assert state.mlflow_active is False


@pytest.mark.unit
def test_state_summary_line_when_nothing_configured(
    reset_settings_observability,
) -> None:
    settings = get_settings()
    settings.langsmith_tracing = False
    settings.langsmith_api_key = None
    settings.langfuse_public_key = None
    settings.langfuse_secret_key = None
    settings.mlflow_tracking_uri = None
    for k in ("LANGSMITH_API_KEY", "LANGCHAIN_API_KEY"):
        os.environ.pop(k, None)

    assert observability_state().summary_line() == "observability: none configured"


@pytest.mark.unit
def test_langsmith_requires_both_tracing_flag_and_key(
    reset_settings_observability,
) -> None:
    """Tracing flag without a key must NOT report active — would mislead operators."""
    settings = get_settings()
    settings.langsmith_tracing = True
    settings.langsmith_api_key = None
    for k in ("LANGSMITH_API_KEY", "LANGCHAIN_API_KEY"):
        os.environ.pop(k, None)

    assert observability_state().langsmith_active is False


@pytest.mark.unit
def test_langsmith_active_when_tracing_and_settings_key(
    reset_settings_observability,
) -> None:
    settings = get_settings()
    settings.langsmith_tracing = True
    settings.langsmith_api_key = SecretStr("ls_test_key")
    for k in ("LANGSMITH_API_KEY", "LANGCHAIN_API_KEY"):
        os.environ.pop(k, None)

    state = observability_state()
    assert state.langsmith_active is True
    assert state.langsmith_project == settings.langsmith_project


@pytest.mark.unit
def test_langsmith_active_when_tracing_and_env_key(
    reset_settings_observability,
) -> None:
    """Env-set key activates LangSmith without needing it in Settings."""
    settings = get_settings()
    settings.langsmith_tracing = True
    settings.langsmith_api_key = None
    os.environ["LANGSMITH_API_KEY"] = "ls_env_key"
    os.environ.pop("LANGCHAIN_API_KEY", None)

    assert observability_state().langsmith_active is True


@pytest.mark.unit
def test_langfuse_inactive_when_only_one_key_set(
    reset_settings_observability,
) -> None:
    """Public-only or secret-only is always misconfiguration — must report inactive."""
    settings = get_settings()
    settings.langfuse_public_key = SecretStr("pk_test")
    settings.langfuse_secret_key = None
    assert observability_state().langfuse_active is False

    settings.langfuse_public_key = None
    settings.langfuse_secret_key = SecretStr("sk_test")
    assert observability_state().langfuse_active is False


@pytest.mark.unit
def test_langfuse_active_when_both_keys_set(
    reset_settings_observability,
) -> None:
    settings = get_settings()
    settings.langfuse_public_key = SecretStr("pk_test")
    settings.langfuse_secret_key = SecretStr("sk_test")
    assert observability_state().langfuse_active is True


@pytest.mark.unit
def test_mlflow_active_when_uri_set(
    reset_settings_observability,
) -> None:
    settings = get_settings()
    settings.mlflow_tracking_uri = "http://mlflow:5000"
    state = observability_state()
    assert state.mlflow_active is True
    assert state.mlflow_uri == "http://mlflow:5000"


@pytest.mark.unit
def test_summary_line_lists_active_integrations(
    reset_settings_observability,
) -> None:
    settings = get_settings()
    settings.langsmith_tracing = True
    settings.langsmith_api_key = SecretStr("ls_key")
    settings.langfuse_public_key = SecretStr("pk")
    settings.langfuse_secret_key = SecretStr("sk")
    settings.mlflow_tracking_uri = "http://mlflow:5000"

    line = observability_state().summary_line()
    assert "LangSmith" in line
    assert "Langfuse" in line
    assert "MLflow" in line


# -- build_callback_handlers --------------------------------------------------


@pytest.mark.unit
def test_build_returns_empty_list_when_nothing_configured(
    reset_settings_observability,
) -> None:
    settings = get_settings()
    settings.langsmith_tracing = False
    settings.langsmith_api_key = None
    settings.langfuse_public_key = None
    settings.langfuse_secret_key = None

    assert build_callback_handlers() == []


@pytest.mark.unit
def test_build_does_not_include_langsmith_handler_explicitly(
    reset_settings_observability,
) -> None:
    """LangSmith works through env-driven activation in langchain itself.

    Including a LangSmith handler in the returned list would double-trace
    every call — once via env activation and once via the explicit handler.
    """
    settings = get_settings()
    settings.langsmith_tracing = True
    settings.langsmith_api_key = SecretStr("ls_key")
    # No Langfuse keys → only LangSmith would be a candidate.
    settings.langfuse_public_key = None
    settings.langfuse_secret_key = None

    assert build_callback_handlers() == []


@pytest.mark.unit
def test_build_skips_langfuse_when_package_missing(
    reset_settings_observability,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Misconfiguration (keys set, package not installed) must degrade gracefully."""
    settings = get_settings()
    settings.langfuse_public_key = SecretStr("pk_test")
    settings.langfuse_secret_key = SecretStr("sk_test")

    # Force the langfuse import path to fail by ensuring the module isn't
    # importable. The simplest way: stub a module that raises on attribute
    # access for `langchain.CallbackHandler`.
    fake_langfuse = types.ModuleType("langfuse")
    fake_langfuse.langchain = types.ModuleType("langfuse.langchain")
    # Don't set CallbackHandler — `from langfuse.langchain import CallbackHandler` will fail.
    monkeypatch.setitem(sys.modules, "langfuse", fake_langfuse)
    monkeypatch.setitem(sys.modules, "langfuse.langchain", fake_langfuse.langchain)

    with caplog.at_level("WARNING"):
        result = build_callback_handlers()
    assert result == []


@pytest.mark.unit
def test_build_includes_langfuse_handler_when_package_present(
    reset_settings_observability,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """When langfuse is importable, a real handler is in the list."""
    settings = get_settings()
    settings.langfuse_public_key = SecretStr("pk_test")
    settings.langfuse_secret_key = SecretStr("sk_test")

    # Inject a fake langfuse.langchain module with a CallbackHandler class.
    fake_langfuse = types.ModuleType("langfuse")
    fake_langchain = types.ModuleType("langfuse.langchain")

    class FakeHandler:
        def __init__(self, *args, **kwargs):
            self.constructed = True

    fake_langchain.CallbackHandler = FakeHandler
    fake_langfuse.langchain = fake_langchain
    monkeypatch.setitem(sys.modules, "langfuse", fake_langfuse)
    monkeypatch.setitem(sys.modules, "langfuse.langchain", fake_langchain)

    handlers = build_callback_handlers()
    assert len(handlers) == 1
    assert isinstance(handlers[0], FakeHandler)


@pytest.mark.unit
def test_build_skips_langfuse_when_handler_construction_fails(
    reset_settings_observability,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Construction failure (bad creds, unreachable host) degrades to no-op."""
    settings = get_settings()
    settings.langfuse_public_key = SecretStr("pk_test")
    settings.langfuse_secret_key = SecretStr("sk_test")

    fake_langfuse = types.ModuleType("langfuse")
    fake_langchain = types.ModuleType("langfuse.langchain")

    class BrokenHandler:
        def __init__(self, *args, **kwargs):
            raise ConnectionError("Langfuse host unreachable")

    fake_langchain.CallbackHandler = BrokenHandler
    fake_langfuse.langchain = fake_langchain
    monkeypatch.setitem(sys.modules, "langfuse", fake_langfuse)
    monkeypatch.setitem(sys.modules, "langfuse.langchain", fake_langchain)

    with caplog.at_level("ERROR"):
        result = build_callback_handlers()
    assert result == []
