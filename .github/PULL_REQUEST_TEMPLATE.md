## Summary

<!-- One or two sentences. What does this change? -->

## Motivation

<!-- Why is this change needed? Link to issue or ADR if applicable. -->

Closes #

## Type of change

- [ ] feat — new functionality
- [ ] fix — bug fix
- [ ] refactor — internal change with no external behaviour shift
- [ ] perf — performance
- [ ] docs — documentation only
- [ ] test — test-only change
- [ ] chore / build / ci — tooling

## Checklist

- [ ] Branch rebased on latest `develop`
- [ ] `ruff check .` and `ruff format --check .` pass
- [ ] `mypy cascade/` passes
- [ ] `pytest -m "not slow"` passes locally
- [ ] New code has tests; coverage on touched files ≥ 85%
- [ ] If agent or eval logic changed: eval gate still green
- [ ] Public API or schema changes documented in `docs/`
- [ ] `CHANGELOG.md` updated under `[Unreleased]`

## Testing notes

<!-- How did you verify this works? Commands run, fixtures used, screenshots if UI. -->

## Risk & rollback

<!-- What could break? How would we revert if it does? -->
