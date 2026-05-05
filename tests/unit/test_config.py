"""Tests for application settings."""

from __future__ import annotations

import pytest

from cascade.config import Settings, get_settings


@pytest.mark.unit
def test_default_environment_is_development() -> None:
    """Settings default to the development environment."""
    settings = Settings(_env_file=None)  # type: ignore[call-arg]
    assert settings.cascade_env == "development"
    assert settings.is_production is False


@pytest.mark.unit
def test_settings_are_cached() -> None:
    """``get_settings()`` returns the same instance on repeated calls."""
    get_settings.cache_clear()
    first = get_settings()
    second = get_settings()
    assert first is second


@pytest.mark.unit
def test_is_production_flag_works() -> None:
    """``is_production`` returns ``True`` only when env is production."""
    settings = Settings(_env_file=None, cascade_env="production")  # type: ignore[call-arg]
    assert settings.is_production is True
