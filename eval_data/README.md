# Evaluation data

Curated datasets that drive the eval gate.

## Files

- `thresholds.yaml` — quality floors. CI fails below these.
- `golden_okrs.jsonl` *(added in Phase 6)* — hand-labeled drafting examples.
- `memory_questions.jsonl` *(added in Phase 6)* — retrieval test set.
- `red_team_attacks.jsonl` *(added in Phase 6)* — adversarial prompts.

## Why these are tracked in Git

These files are part of the contract. Changes to them are reviewed like code changes,
and the eval gate runs deterministically because the inputs don't drift. PII and
customer data never enter this directory.

## Adding new examples

1. Author the example in the appropriate `.jsonl` file.
2. Run the eval suite locally (`python -m cascade.evals.gate --output local.json`).
3. Confirm scores didn't drop below thresholds.
4. Submit a PR with the new examples and a one-line note in the PR description.

If a new example exposes a regression, fix the regression first and ship the new
example with the fix.
