# cascade.evals

Regression eval suite that gates merges in CI. Three eval families measure
different layers of the system; threshold floors live in
`eval_data/thresholds.yaml`.

## The three families

| Family | What it measures | Threshold | Dataset |
|---|---|---|---|
| `drafting_f1` | Critic verdict agreement on the golden dataset | 0.85 | 30 cases |
| `retrieval_f1` | Hybrid retrieval F1 on memory questions | 0.90 | 10 cases |
| `red_team_pass_rate` | Adversarial robustness | 0.95 | 6 cases |

## Files

```
evals/
├── __init__.py         Public API
├── types.py            CaseResult, MetricResult, EvalReport
├── datasets.py         Strict JSONL loaders for the three datasets
├── drafting.py         Drafter + Critic agreement; per-class F1 metadata
├── retrieval.py        Precision-at-K + recall against expected_relevant_ids
├── red_team.py         Per-attack-type dispatch
├── gate.py             Runner — produces the EvalReport
└── check_thresholds.py Threshold checker — gates merges
```

Datasets live in `eval_data/` at the repo root, not in this module — they're
not Python and shouldn't be imported as such.

## Two-step gating

```
            ┌──────────────────────────────────┐
            │  python -m cascade.evals.gate    │
            │                                  │
            │  Runs all three families,        │
            │  produces eval_results.json,     │
            │  ALWAYS exits 0                  │
            └─────────────┬────────────────────┘
                          │
                          ▼
                ┌──────────────────────┐
                │  Upload as artifact  │  ← preserved regardless of gate result
                └─────────┬────────────┘
                          │
                          ▼
            ┌──────────────────────────────────────────┐
            │  python -m cascade.evals.check_thresholds│
            │                                          │
            │  Reads the report, compares to           │
            │  thresholds, exits non-zero on regression│
            └──────────────────────────────────────────┘
```

The runner exiting 0 even on metric failure is intentional. We want the report
uploadable as a CI artifact regardless of pass/fail — diagnosing a regression
requires the report, and uploading it inside a failed step is brittle.

## --use-fakes mode

Swaps `FakeChatModel` in for the real LLM. Verifies harness wiring without
consuming Groq quota:

- Datasets parse
- Eval modules call into Drafter / Critic / retrieval correctly
- Runner produces a valid `EvalReport`
- Threshold checker reads it correctly

Fake-mode metrics will fail thresholds (canned responses don't match diverse
intents). That's expected and documented in the runbook.

## Adding a case

1. Append a JSON line to the appropriate `eval_data/*.jsonl` file
2. Run the dataset test to validate the schema:
   ```bash
   pytest tests/unit/test_evals_datasets.py
   ```
3. Run the case end-to-end:
   ```bash
   python -m cascade.evals.gate --filter drafting --case-id your-id
   ```
4. Open a PR; CI runs the full suite

## Adding a new family

1. Create `cascade/evals/<family>.py` exposing `evaluate_<family>()` returning
   a `MetricResult`
2. Add a threshold to `eval_data/thresholds.yaml` and a corresponding field
   to `cascade.evals.datasets.Thresholds`
3. Wire it into `cascade.evals.gate.run_evals()`
4. Add a row to the table in [`docs/runbooks/eval-gate.md`](../../docs/runbooks/eval-gate.md)

## Per-class F1 in metadata

Drafting eval emits per-class F1 scores in metric metadata so a CI failure
points at the specific verdict class that regressed:

```json
{
  "name": "drafting_f1",
  "score": 0.733,
  "threshold": 0.85,
  "metadata": {
    "f1_pass": 0.9,
    "f1_needs_revision": 0.6,    ← regressed here
    "f1_reject": 0.7,
    "f1_macro": 0.733
  }
}
```

PR comments surface the macro F1; investigation goes to the per-class breakdown.

## Verdict normalisation interaction

The eval gate respects the same verdict normalisation the agents apply. If the
LLM returns `pass` but a dimension score is below 0.7, the Critic forces
`needs_revision` — and the eval grades against that normalised verdict, not
the raw LLM output. This is correct: we want to gate on the system's actual
behaviour, not on the model's raw response.

## Testing

- `tests/unit/test_evals_datasets.py` — 11 tests on dataset loaders
- `tests/unit/test_evals.py` — 13 tests on the three eval modules
- `tests/unit/test_evals_runner.py` — 8 tests on the runner and threshold
  checker including the `--use-fakes` smoke path

## See also

- [Eval gate runbook](../../docs/runbooks/eval-gate.md)
- [Architecture: evals](../../docs/architecture/evals.md)
- [.github/workflows/eval-gate.yml](../../.github/workflows/eval-gate.yml)
