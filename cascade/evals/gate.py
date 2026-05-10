"""Eval gate runner.

Run from the command line::

    python -m cascade.evals.gate --output eval_results.json
    python -m cascade.evals.gate --filter drafting --case-id good-001 --verbose
    python -m cascade.evals.gate --output eval_results.json --use-fakes

CI invokes this in the ``eval-gate.yml`` workflow on every PR that touches
agent or eval code. ``check_thresholds.py`` reads the produced JSON and
exits non-zero on regression.

The runner emits a report regardless of pass/fail status — failed runs are
inspectable. Threshold gating is intentionally a *separate* step so the report
is preserved and uploaded as a CI artifact even when CI fails.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import sys
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING

from cascade._version import __version__
from cascade.agents.llm import FakeChatModel, get_chat_model
from cascade.config import get_settings
from cascade.evals.datasets import (
    load_golden_okrs,
    load_memory_questions,
    load_red_team,
    load_thresholds,
)
from cascade.evals.drafting import evaluate_drafting
from cascade.evals.red_team import evaluate_red_team
from cascade.evals.retrieval import evaluate_retrieval
from cascade.evals.types import EvalReport, MetricResult

if TYPE_CHECKING:
    from langchain_core.language_models import BaseChatModel

logger = logging.getLogger(__name__)


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="cascade-eval-gate",
        description="Run the cascade eval suite and write a JSON report.",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("eval_results.json"),
        help="Path for the JSON report (default: ./eval_results.json).",
    )
    parser.add_argument(
        "--filter",
        choices=["drafting", "retrieval", "red_team"],
        action="append",
        default=None,
        help="Run only the listed metric(s). Repeatable.",
    )
    parser.add_argument(
        "--case-id",
        action="append",
        default=None,
        help="Restrict to specific case ids. Repeatable.",
    )
    parser.add_argument(
        "--use-fakes",
        action="store_true",
        help=(
            "Use FakeChatModel with deterministic canned responses. Useful for "
            "CI smoke testing the harness itself, and for plumbing tests when "
            "no GROQ_API_KEY is configured."
        ),
    )
    parser.add_argument(
        "-v",
        "--verbose",
        action="store_true",
        help="Verbose logging.",
    )
    return parser.parse_args(argv)


async def run_evals(
    *,
    model: BaseChatModel,
    metric_filter: list[str] | None,
    case_ids: list[str] | None,
) -> EvalReport:
    """Run the eval suite and return the structured report.

    When ``MLFLOW_TRACKING_URI`` is configured the run is wrapped in an
    MLflow run context: metrics, params, and a summary tag are logged.
    Without MLflow configured the wrapper is a no-op and behaviour is
    unchanged.
    """
    from cascade.observability import log_metrics, log_params, mlflow_run

    thresholds = load_thresholds()
    started_at = datetime.now(tz=UTC)
    metrics: dict[str, MetricResult] = {}

    run_name = f"eval-gate-{started_at.strftime('%Y%m%dT%H%M%SZ')}"
    tags = {
        "cascade.version": __version__,
        "cascade.surface": "eval-gate",
    }

    with mlflow_run(run_name, tags=tags):
        log_params(
            {
                "metric_filter": metric_filter or "all",
                "case_filter": case_ids or "all",
                "groq_model": getattr(model, "model_name", "unknown"),
                "drafting_threshold_f1": thresholds.drafting["f1_min"],
                "retrieval_threshold_faithfulness": thresholds.retrieval["faithfulness_min"],
                "red_team_threshold_pass_rate": thresholds.red_team["pass_rate_min"],
            }
        )

        if metric_filter is None or "drafting" in metric_filter:
            cases = load_golden_okrs()
            if case_ids:
                cases = [c for c in cases if c.id in case_ids]
            if cases:
                metrics["drafting_f1"] = await evaluate_drafting(
                    cases=cases,
                    model=model,
                    threshold=thresholds.drafting["f1_min"],
                )

        if metric_filter is None or "retrieval" in metric_filter:
            cases = load_memory_questions()
            if case_ids:
                cases = [c for c in cases if c.id in case_ids]
            if cases:
                metrics["retrieval_f1"] = await evaluate_retrieval(
                    cases=cases,
                    threshold=thresholds.retrieval["faithfulness_min"],
                )

        if metric_filter is None or "red_team" in metric_filter:
            cases = load_red_team()
            if case_ids:
                cases = [c for c in cases if c.id in case_ids]
            if cases:
                metrics["red_team_pass_rate"] = await evaluate_red_team(
                    cases=cases,
                    model=model,
                    threshold=thresholds.red_team["pass_rate_min"],
                )

        # Flat numeric metrics for MLflow's metric API. Each MetricResult
        # has a `score` field; the eval gate's UI groups by metric name.
        log_metrics({name: result.score for name, result in metrics.items()})
        log_metrics(
            {f"{name}_passed": 1.0 if result.passed else 0.0 for name, result in metrics.items()}
        )

    finished_at = datetime.now(tz=UTC)
    return EvalReport(
        run_id=str(uuid.uuid4()),
        started_at=started_at,
        finished_at=finished_at,
        cascade_version=__version__,
        metrics=metrics,
    )


def _build_fake_model() -> FakeChatModel:
    """A FakeChatModel with enough canned responses for the full suite.

    The fake produces deterministic outputs sized to the dataset — letting CI
    smoke-test the harness without consuming Groq quota. Real evaluation runs
    against the live model.
    """
    # Generic 'good' proposal and 'pass' critique repeated for each invocation.
    # The drafting eval will mostly fail against a real Critic because the
    # drafted OKR doesn't actually match the case intent — that's expected
    # for fake mode and is documented in the runbook.
    proposal = json.dumps(
        {
            "title": "Reach product-market fit in the SMB segment this quarter",
            "description": None,
            "key_results": [
                {
                    "description": "Lift weekly active accounts from 200 to 800",
                    "metric_type": "number",
                    "baseline_value": 200,
                    "target_value": 800,
                    "current_value": 200,
                    "unit": "accounts",
                    "weight": 1.0,
                }
            ],
        }
    )
    critique = json.dumps(
        {
            "specificity": {"score": 0.85, "reasoning": "concrete"},
            "measurability": {"score": 0.9, "reasoning": "quantified"},
            "ambition": {"score": 0.8, "reasoning": "stretch"},
            "structure": {"score": 0.9, "reasoning": "fits convention"},
            "vague_phrases": [],
            "verdict": "pass",
            "suggestions": [],
        }
    )
    # 50 of each is enough for any reasonably-sized dataset.
    responses: list[str] = []
    for _ in range(50):
        responses.append(proposal)
        responses.append(critique)
    return FakeChatModel(responses=responses)


def main(argv: list[str] | None = None) -> int:
    """Run the eval gate and write the report. Returns process exit code."""
    args = _parse_args(argv)
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        stream=sys.stderr,
    )

    from cascade.observability import observability_state

    logger.info(observability_state().summary_line())

    if args.use_fakes:
        model: BaseChatModel = _build_fake_model()
        logger.info("running eval gate with FakeChatModel")
    else:
        try:
            model = get_chat_model(get_settings())
        except RuntimeError as exc:
            logger.error("cannot construct chat model: %s", exc)
            logger.error("re-run with --use-fakes to smoke-test the harness only")
            return 1

    try:
        report = asyncio.run(
            run_evals(
                model=model,
                metric_filter=args.filter,
                case_ids=args.case_id,
            )
        )
    except Exception:
        logger.exception("eval gate run failed")
        return 1

    args.output.write_text(report.model_dump_json(indent=2), encoding="utf-8")
    logger.info("wrote eval report to %s", args.output)

    if report.all_passed:
        logger.info("all metrics passed")
        return 0
    failed = [m.name for m in report.metrics.values() if not m.passed]
    logger.warning("eval gate failed: %s", failed)
    # The runner exits 0 even on metric failure — threshold checker is the gate.
    # This split keeps the report uploadable as a CI artifact.
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
