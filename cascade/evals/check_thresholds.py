"""Threshold checker — gates merges in CI based on the eval report.

Reads ``eval_results.json`` produced by ``cascade.evals.gate`` and exits
non-zero if any metric fell below its configured threshold. Run as the second
step in the eval-gate workflow so the report is preserved (uploaded as an
artifact) regardless of pass/fail.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from cascade.evals.types import EvalReport


def main(argv: list[str] | None = None) -> int:
    """Check thresholds in the eval report. Returns process exit code."""
    parser = argparse.ArgumentParser(
        prog="cascade-eval-check",
        description="Check eval results against thresholds and exit non-zero on regression.",
    )
    parser.add_argument(
        "report",
        type=Path,
        help="Path to the eval_results.json produced by cascade.evals.gate.",
    )
    args = parser.parse_args(argv)

    if not args.report.exists():
        print(f"error: report not found: {args.report}", file=sys.stderr)
        return 2

    payload = json.loads(args.report.read_text(encoding="utf-8"))
    report = EvalReport.model_validate(payload)

    failed: list[str] = []
    print(f"cascade {report.cascade_version} — {len(report.metrics)} metrics")
    print(f"run_id: {report.run_id}")
    print()
    print(f"{'Metric':<28} {'Score':>8} {'Threshold':>10}  Status")
    print("-" * 60)
    for name, metric in report.metrics.items():
        status = "PASS" if metric.passed else "FAIL"
        if not metric.passed:
            failed.append(name)
        print(f"{name:<28} {metric.score:>8.3f} {metric.threshold:>10.3f}  {status}")
    print()

    if not failed:
        print("All metrics cleared their thresholds.")
        return 0

    print(f"Threshold breach in {len(failed)} metric(s):")
    for name in failed:
        metric = report.metrics[name]
        cases_failed = [c for c in metric.cases if not c.passed]
        print(f"  - {name}: scored {metric.score:.3f}, threshold {metric.threshold:.3f}")
        if cases_failed:
            print(f"    {len(cases_failed)} failing case(s):")
            for case in cases_failed[:5]:
                print(f"      * {case.case_id}: expected={case.expected!r} actual={case.actual!r}")
            if len(cases_failed) > 5:
                print(f"      ... and {len(cases_failed) - 5} more")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
