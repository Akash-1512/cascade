"""Drafting eval — measures Critic verdict agreement on the golden dataset.

For each :class:`GoldenOKRCase`:

1. Run the Drafter on ``intent``
2. Run the Critic on the resulting proposal
3. Compare the Critic's verdict to ``expected_verdict``
4. If ``expected_min_score`` is set, verify the overall_score is at least that
5. If ``expected_max_score`` is set, verify the overall_score is at most that

The aggregate score is the fraction of cases where verdict matches AND score
constraints (if any) are satisfied. F1 across the three verdict classes is
included as metadata for diagnostic value.
"""

from __future__ import annotations

import logging
import time
from collections import Counter
from typing import TYPE_CHECKING

from cascade.agents.critic import critique_proposal
from cascade.agents.drafter import DrafterError, draft_objective
from cascade.evals.datasets import GoldenOKRCase
from cascade.evals.types import CaseResult, MetricResult

if TYPE_CHECKING:
    from langchain_core.language_models import BaseChatModel

logger = logging.getLogger(__name__)


async def evaluate_drafting(
    *,
    cases: list[GoldenOKRCase],
    model: BaseChatModel,
    threshold: float,
) -> MetricResult:
    """Run the drafting eval over the given cases."""
    results: list[CaseResult] = []
    started = time.monotonic()

    for case in cases:
        try:
            proposal = await draft_objective(intent=case.intent, model=model)
            critique = await critique_proposal(proposal=proposal, model=model)
        except DrafterError as exc:
            # Drafter rejecting outright is consistent with an expected reject
            # verdict; for other expected verdicts it is a failure.
            passed = case.expected_verdict == "reject"
            results.append(
                CaseResult(
                    case_id=case.id,
                    passed=passed,
                    score=1.0 if passed else 0.0,
                    expected=case.expected_verdict,
                    actual="drafter_error",
                    notes=f"Drafter raised: {exc}",
                )
            )
            continue

        verdict_match = critique.verdict == case.expected_verdict
        score_match = _score_in_range(critique.overall_score, case)
        passed = verdict_match and score_match

        results.append(
            CaseResult(
                case_id=case.id,
                passed=passed,
                score=1.0 if passed else 0.0,
                expected=case.expected_verdict,
                actual=critique.verdict,
                notes=(
                    f"score={critique.overall_score:.3f}"
                    + (
                        f", expected≥{case.expected_min_score}"
                        if case.expected_min_score is not None
                        else ""
                    )
                    + (
                        f", expected≤{case.expected_max_score}"
                        if case.expected_max_score is not None
                        else ""
                    )
                ),
            )
        )

    elapsed = time.monotonic() - started
    accuracy = sum(1 for r in results if r.passed) / max(1, len(results))

    f1_metadata = _verdict_f1(cases, results)

    return MetricResult(
        name="drafting_f1",
        score=accuracy,
        threshold=threshold,
        cases=results,
        metadata={
            "total_cases": len(results),
            "elapsed_seconds": round(elapsed, 2),
            **{f"f1_{k}": round(v, 3) for k, v in f1_metadata.items()},
        },
    )


def _score_in_range(actual: float, case: GoldenOKRCase) -> bool:
    """Verify the Critic's overall_score satisfies any min/max constraints."""
    if case.expected_min_score is not None and actual < case.expected_min_score:
        return False
    return not (case.expected_max_score is not None and actual > case.expected_max_score)


def _verdict_f1(cases: list[GoldenOKRCase], results: list[CaseResult]) -> dict[str, float]:
    """F1 per verdict class (pass / needs_revision / reject)."""
    by_id = {c.id: c for c in cases}
    expected: list[str] = []
    actual: list[str] = []
    for r in results:
        case = by_id.get(r.case_id)
        if case is None:
            continue
        expected.append(case.expected_verdict)
        actual.append(str(r.actual) if r.actual is not None else "missing")

    f1: dict[str, float] = {}
    for verdict in ("pass", "needs_revision", "reject"):
        tp = sum(1 for e, a in zip(expected, actual, strict=True) if e == verdict and a == verdict)
        fp = sum(1 for e, a in zip(expected, actual, strict=True) if e != verdict and a == verdict)
        fn = sum(1 for e, a in zip(expected, actual, strict=True) if e == verdict and a != verdict)
        precision = tp / (tp + fp) if (tp + fp) > 0 else 0.0
        recall = tp / (tp + fn) if (tp + fn) > 0 else 0.0
        f1_class = (
            2 * precision * recall / (precision + recall) if (precision + recall) > 0 else 0.0
        )
        f1[verdict] = f1_class

    # Macro F1 for the suite-level diagnostic
    counts: Counter[str] = Counter(expected)
    total = sum(counts.values())
    f1["macro"] = sum(f1[v] * counts[v] for v in counts) / max(1, total)
    return f1
