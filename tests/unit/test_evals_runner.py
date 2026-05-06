"""Tests for :mod:`cascade.evals.gate` and :mod:`cascade.evals.check_thresholds`."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

from cascade.evals import check_thresholds as check_module
from cascade.evals.gate import _build_fake_model, main
from cascade.evals.types import CaseResult, EvalReport, MetricResult


@pytest.mark.unit
def test_runner_with_fakes_writes_report(tmp_path: Path) -> None:
    """End-to-end smoke test: the runner produces a parseable JSON report."""
    output = tmp_path / "report.json"
    rc = main(["--use-fakes", "--output", str(output)])
    assert rc == 0
    assert output.exists()
    payload = json.loads(output.read_text())
    report = EvalReport.model_validate(payload)
    assert "drafting_f1" in report.metrics
    assert "retrieval_f1" in report.metrics
    assert "red_team_pass_rate" in report.metrics


@pytest.mark.unit
def test_runner_filter_runs_only_selected_metrics(tmp_path: Path) -> None:
    output = tmp_path / "report.json"
    rc = main(["--use-fakes", "--output", str(output), "--filter", "retrieval"])
    assert rc == 0
    report = EvalReport.model_validate(json.loads(output.read_text()))
    assert set(report.metrics.keys()) == {"retrieval_f1"}


@pytest.mark.unit
def test_runner_case_id_filter_restricts_dataset(tmp_path: Path) -> None:
    output = tmp_path / "report.json"
    rc = main(
        [
            "--use-fakes",
            "--output",
            str(output),
            "--filter",
            "drafting",
            "--case-id",
            "good-001",
        ]
    )
    assert rc == 0
    report = EvalReport.model_validate(json.loads(output.read_text()))
    assert len(report.metrics["drafting_f1"].cases) == 1


@pytest.mark.unit
def test_runner_returns_zero_even_on_metric_failure(tmp_path: Path) -> None:
    """The runner exits 0 even when metrics fail — threshold checker is the gate.

    This split keeps the report uploadable as a CI artifact.
    """
    output = tmp_path / "report.json"
    rc = main(["--use-fakes", "--output", str(output)])
    # Fakes will fail thresholds, but the runner still exits 0.
    assert rc == 0
    report = EvalReport.model_validate(json.loads(output.read_text()))
    assert not report.all_passed


@pytest.mark.unit
def test_build_fake_model_provides_enough_responses() -> None:
    model = _build_fake_model()
    # Need at least 60 responses for the 30-case drafting set (proposal + critique each)
    assert len(model.responses) >= 60


@pytest.mark.unit
def test_check_thresholds_passes_when_all_clear(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    report = EvalReport(
        run_id="r1",
        started_at=datetime.now(tz=UTC),
        finished_at=datetime.now(tz=UTC),
        cascade_version="0.7.0",
        metrics={
            "drafting_f1": MetricResult(
                name="drafting_f1",
                score=0.9,
                threshold=0.85,
                cases=[],
            ),
        },
    )
    path = tmp_path / "report.json"
    path.write_text(report.model_dump_json())
    rc = check_module.main([str(path)])
    assert rc == 0
    captured = capsys.readouterr()
    assert "All metrics cleared" in captured.out


@pytest.mark.unit
def test_check_thresholds_fails_on_regression(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    report = EvalReport(
        run_id="r1",
        started_at=datetime.now(tz=UTC),
        finished_at=datetime.now(tz=UTC),
        cascade_version="0.7.0",
        metrics={
            "drafting_f1": MetricResult(
                name="drafting_f1",
                score=0.5,
                threshold=0.85,
                cases=[
                    CaseResult(
                        case_id="good-001",
                        passed=False,
                        score=0.0,
                        expected="pass",
                        actual="needs_revision",
                    ),
                ],
            ),
        },
    )
    path = tmp_path / "report.json"
    path.write_text(report.model_dump_json())
    rc = check_module.main([str(path)])
    assert rc == 1
    captured = capsys.readouterr()
    assert "Threshold breach" in captured.out
    assert "good-001" in captured.out


@pytest.mark.unit
def test_check_thresholds_missing_report_returns_two(tmp_path: Path) -> None:
    rc = check_module.main([str(tmp_path / "does-not-exist.json")])
    assert rc == 2
