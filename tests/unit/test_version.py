"""Tests for the version module."""

from __future__ import annotations

import re

import pytest

from cascade import __version__


@pytest.mark.unit
def test_version_is_a_string() -> None:
    """Version is exposed as a string."""
    assert isinstance(__version__, str)


@pytest.mark.unit
def test_version_follows_semver() -> None:
    """Version follows SemVer 2.0.0 — MAJOR.MINOR.PATCH with optional pre-release."""
    semver = re.compile(
        r"^(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)"
        r"(?:-((?:0|[1-9]\d*|\d*[a-zA-Z-][0-9a-zA-Z-]*)"
        r"(?:\.(?:0|[1-9]\d*|\d*[a-zA-Z-][0-9a-zA-Z-]*))*))?"
        r"(?:\+([0-9a-zA-Z-]+(?:\.[0-9a-zA-Z-]+)*))?$"
    )
    assert semver.match(__version__) is not None, f"Invalid SemVer: {__version__}"
