"""Smoke-check that the Helm chart is structurally valid.

This is a unit test rather than an integration test because it doesn't
need helm itself or a Kubernetes cluster — it just parses YAML and scans
template files. Catches the most common chart-drift issues (missing
template files, unbalanced ``{{- if/end -}}`` blocks, helper references
that don't resolve) on every PR.

CI also runs ``helm lint`` in a separate job; this test is the cheap
pre-check that fires inside the standard pytest run.
"""

from __future__ import annotations

import pytest

from scripts.validate_helm_chart import validate


@pytest.mark.unit
def test_helm_chart_passes_structural_validation() -> None:
    """The chart in helm/cascade/ must satisfy every structural check.

    Any error here means the chart would fail to install. Warnings are
    fine (unused helpers, defined-but-unreferenced templates) but errors
    block CI; that's the deliberate gradient.
    """
    result = validate()

    assert result.ok, "Helm chart validation errors:\n" + "\n".join(
        f"  - {e}" for e in result.errors
    )
