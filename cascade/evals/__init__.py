"""cascade eval suite.

Three eval families gate merges in CI:

- **drafting** — Drafter + Critic verdict agreement on a 30-case golden dataset
- **retrieval** — Hybrid retrieval F1 on a 10-case memory question dataset
- **red_team** — Adversarial robustness across six attack types

Run from the command line::

    python -m cascade.evals.gate                            # full live run
    python -m cascade.evals.gate --use-fakes                # plumbing smoke test
    python -m cascade.evals.gate --filter drafting          # one metric only

Threshold gating is a separate step::

    python -m cascade.evals.check_thresholds eval_results.json
"""

from cascade.evals.datasets import (
    GoldenOKRCase,
    MemoryQueryCase,
    RedTeamCase,
    Thresholds,
    load_golden_okrs,
    load_memory_questions,
    load_red_team,
    load_thresholds,
)
from cascade.evals.types import CaseResult, EvalReport, MetricResult

__all__ = [
    "CaseResult",
    "EvalReport",
    "GoldenOKRCase",
    "MemoryQueryCase",
    "MetricResult",
    "RedTeamCase",
    "Thresholds",
    "load_golden_okrs",
    "load_memory_questions",
    "load_red_team",
    "load_thresholds",
]
