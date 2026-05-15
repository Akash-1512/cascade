"""Structural validation of the cascade Helm chart.

helm is the source of truth — ``helm lint`` and ``helm template`` should
run in CI. This script is a cheap pre-check that catches the most common
mistakes (unbalanced template blocks, missing required Chart.yaml keys,
template files that reference helpers that don't exist) without needing
helm itself installed.

It runs in two modes:

  - Structural: parse Chart.yaml and values.yaml as plain YAML; check
    that every required key is present; check that every templates/*.yaml
    file has balanced ``{{- if/end -}}`` blocks and matching ``{{`` / ``}}``.

  - Helper-reference: scan every ``include "cascade.X"`` call across the
    templates; assert that ``X`` is defined in _helpers.tpl. Catches typos
    that helm would only surface at template-render time.

Used by tests/unit/test_helm_chart.py. Doesn't replace ``helm lint`` — it
catches a strict subset of issues — but it's enough to keep the chart
green without requiring helm in the local dev venv.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

import yaml

CHART_ROOT = Path("helm/cascade")
TEMPLATES_DIR = CHART_ROOT / "templates"
HELPERS_FILE = TEMPLATES_DIR / "_helpers.tpl"


@dataclass
class ValidationResult:
    """Aggregate of structural validation findings."""

    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.errors


def validate() -> ValidationResult:
    """Run every check; aggregate errors and warnings."""
    result = ValidationResult()

    _check_chart_yaml(result)
    _check_values_yaml(result)
    _check_template_blocks(result)
    _check_helper_references(result)
    _check_required_templates(result)

    return result


def _check_chart_yaml(result: ValidationResult) -> None:
    """Chart.yaml must have apiVersion v2, name, version, type, appVersion."""
    chart_path = CHART_ROOT / "Chart.yaml"
    if not chart_path.exists():
        result.errors.append(f"missing {chart_path}")
        return
    try:
        chart = yaml.safe_load(chart_path.read_text())
    except yaml.YAMLError as e:
        result.errors.append(f"Chart.yaml is not valid YAML: {e}")
        return

    required = ["apiVersion", "name", "version", "type", "appVersion"]
    for key in required:
        if key not in chart:
            result.errors.append(f"Chart.yaml: missing required key {key!r}")

    if chart.get("apiVersion") != "v2":
        result.errors.append(
            f"Chart.yaml: apiVersion must be 'v2' (Helm 3); got {chart.get('apiVersion')!r}"
        )

    if chart.get("type") not in ("application", "library"):
        result.errors.append(
            f"Chart.yaml: type must be 'application' or 'library'; got {chart.get('type')!r}"
        )


def _check_values_yaml(result: ValidationResult) -> None:
    """values.yaml must parse and provide the keys the templates reference."""
    values_path = CHART_ROOT / "values.yaml"
    if not values_path.exists():
        result.errors.append(f"missing {values_path}")
        return
    try:
        values = yaml.safe_load(values_path.read_text())
    except yaml.YAMLError as e:
        result.errors.append(f"values.yaml is not valid YAML: {e}")
        return

    # Top-level keys our templates consume. Missing any of these would
    # produce a render error at install time.
    required_top_level = [
        "image",
        "api",
        "mcp",
        "ui",
        "secrets",
        "config",
        "postgresql",
        "externalDatabase",
        "serviceAccount",
    ]
    for key in required_top_level:
        if key not in values:
            result.errors.append(f"values.yaml: missing top-level key {key!r}")


def _check_template_blocks(result: ValidationResult) -> None:
    """Every template file's ``{{- if/end -}}`` blocks must balance."""
    for path in sorted(TEMPLATES_DIR.glob("*.yaml")):
        text = path.read_text()
        opens = len(re.findall(r"\{\{-?\s*if\b", text))
        opens += len(re.findall(r"\{\{-?\s*range\b", text))
        opens += len(re.findall(r"\{\{-?\s*with\b", text))
        opens += len(re.findall(r"\{\{-?\s*define\b", text))
        closes = len(re.findall(r"\{\{-?\s*end\b", text))
        if opens != closes:
            result.errors.append(
                f"{path}: unbalanced if/range/with/define blocks ({opens} opens, {closes} ends)"
            )
        # Cheap brace count
        if text.count("{{") != text.count("}}"):
            result.errors.append(
                f"{path}: unbalanced {{{{ }}}} ({text.count('{{')} vs {text.count('}}')})"
            )


def _check_helper_references(result: ValidationResult) -> None:
    """Every ``include "cascade.X"`` must reference a defined helper."""
    if not HELPERS_FILE.exists():
        result.errors.append(f"missing helpers file: {HELPERS_FILE}")
        return

    helpers_text = HELPERS_FILE.read_text()
    defined: set[str] = set()
    for match in re.finditer(r'\{\{-?\s*define\s+"(cascade\.[\w.]+)"\s*-?\}\}', helpers_text):
        defined.add(match.group(1))

    if not defined:
        result.warnings.append(f"{HELPERS_FILE}: no helpers defined")
        return

    # Scan every template file for include calls. Includes can appear
    # anywhere — at the start of a {{...}} block, nested inside (include
    # ...) parens for argument passing, or even cross-referenced from
    # _helpers.tpl itself (cascade.labels calls cascade.chart). Match
    # the include call wherever it appears.
    used: set[str] = set()
    scan_paths = [
        *sorted(TEMPLATES_DIR.glob("*.yaml")),
        *sorted(TEMPLATES_DIR.glob("*.tpl")),
        TEMPLATES_DIR / "NOTES.txt",
    ]
    include_pattern = re.compile(r'include\s+"(cascade\.[\w.]+)"')
    for path in scan_paths:
        if not path.exists():
            continue
        for match in include_pattern.finditer(path.read_text()):
            used.add(match.group(1))

    missing = used - defined
    for name in sorted(missing):
        result.errors.append(
            f"helper {name!r} is referenced by a template but not defined in _helpers.tpl"
        )

    unused = defined - used
    for name in sorted(unused):
        result.warnings.append(f"helper {name!r} is defined but not referenced by any template")


def _check_required_templates(result: ValidationResult) -> None:
    """The chart needs at least these template files to do its job."""
    required = [
        "_helpers.tpl",
        "serviceaccount.yaml",
        "configmap.yaml",
        "secret.yaml",
        "api-deployment.yaml",
        "mcp-deployment.yaml",
        "ui-deployment.yaml",
        "NOTES.txt",
    ]
    for name in required:
        if not (TEMPLATES_DIR / name).exists():
            result.errors.append(f"missing required template: templates/{name}")


def main() -> int:
    """CLI entrypoint — prints findings, exits non-zero on errors."""
    result = validate()
    for warning in result.warnings:
        print(f"  WARN  {warning}")
    for error in result.errors:
        print(f"  FAIL  {error}")
    if result.ok:
        print(f"Helm chart structural check passed ({len(result.warnings)} warnings)")
        return 0
    print(f"\nHelm chart structural check FAILED ({len(result.errors)} errors)")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
