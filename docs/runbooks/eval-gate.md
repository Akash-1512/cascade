# Eval gate

cascade ships with a regression eval suite that gates merges in CI. Three eval
families measure different layers of the system:

| Family | What it measures | Threshold |
|---|---|---|
| `drafting_f1` | Critic verdict agreement on the 30-case golden dataset | 0.85 |
| `retrieval_f1` | Hybrid retrieval F1 on 10 memory-question cases | 0.90 |
| `red_team_pass_rate` | Adversarial robustness across 6 attack types | 0.95 |

Thresholds live in [`eval_data/thresholds.yaml`](../../eval_data/thresholds.yaml).
Loosening a threshold requires an ADR; raising one comes with a two-week grace
period (see CONTRIBUTING.md).

## Running locally

```bash
# Full live run (requires GROQ_API_KEY)
python -m cascade.evals.gate

# Plumbing smoke test — no API key needed, deterministic
python -m cascade.evals.gate --use-fakes

# One metric only
python -m cascade.evals.gate --filter drafting

# One case only
python -m cascade.evals.gate --filter drafting --case-id good-007

# Custom output path
python -m cascade.evals.gate --output /tmp/my_run.json
```

After the runner finishes, check thresholds:

```bash
python -m cascade.evals.check_thresholds eval_results.json
```

Exit code is the gate: `0` for pass, `1` for any threshold breach, `2` for a
missing report file.

## Why two steps

The runner exits 0 even when metrics fail. The threshold checker is the actual
gate. This split exists because we want the report uploadable as a CI artifact
*regardless* of whether thresholds passed — diagnosing a regression requires
the report, and uploading it inside a failed step is brittle in some Actions
configurations.

## What `--use-fakes` actually tests

`--use-fakes` swaps `FakeChatModel` in for the real LLM. This is enough to
verify that:

- The dataset files parse
- The harness wires up correctly (Drafter → Critic → metric aggregation)
- The runner produces a valid `EvalReport`
- The threshold checker reads it correctly

It does **not** measure model quality. Fake-mode metrics will fail thresholds
because the canned responses don't match the diverse intents in the dataset —
that's expected and is why the workflow runs the threshold check only when a
real key is configured.

## Datasets

### `eval_data/golden_okrs.jsonl` — 30 cases

10 each of `pass`, `needs_revision`, `reject` verdicts across 9 functional
roles. Each case has:

- `id`, `role`, `intent` — the input
- `expected_verdict` — what the Critic should return
- `expected_min_score` / `expected_max_score` — Critic score constraints
- `rationale` — why this is the expected outcome

### `eval_data/memory_questions.jsonl` — 10 cases

Each case is self-contained: it ships with its own `context_chunks` corpus and
the `expected_relevant_ids` from that corpus. The retrieval eval builds an
`InMemoryStore` per case so runs are reproducible bit-for-bit.

### `eval_data/red_team_attacks.jsonl` — 6 cases

Six attack types:

- `vague_okr_injection`, `sandbagging`, `target_gaming` — Critic must flag
- `prompt_injection_via_intent` — Drafter must ignore the injection
- `decision_laundering`, `memory_poisoning` — structurally inert at Drafter
  level (Drafter has no write authority); we verify normal proposals come
  back unchanged

## Adding a case

1. Append a JSON line to the relevant `eval_data/*.jsonl` file
2. Run the appropriate dataset test to confirm the schema validates:
   `pytest tests/unit/test_evals_datasets.py`
3. Run the eval locally with `--case-id` to see the case execute end-to-end:
   `python -m cascade.evals.gate --filter drafting --case-id your-id-001`
4. Open a PR; CI runs the full suite

## Adding a new eval family

1. Create `cascade/evals/<family>.py` exposing `evaluate_<family>()` returning
   a `MetricResult`
2. Add a threshold to `eval_data/thresholds.yaml` and the corresponding field
   to `cascade.evals.datasets.Thresholds`
3. Wire it into `cascade/evals/gate.py` `run_evals()`
4. Add a row to the table at the top of this runbook

## Troubleshooting

**`error: report not found`** — the runner did not produce a report. Re-run with
`-v` to see the underlying exception.

**`Threshold breach in N metric(s)`** — expected during regression. The
threshold checker prints the top 5 failing case ids per metric so you can drill
in with `--case-id`.

**`cannot construct chat model`** — `GROQ_API_KEY` is missing and you didn't
pass `--use-fakes`. Add the key, or use fakes for plumbing checks.
