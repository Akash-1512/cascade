# Static typing

cascade declares strict mypy in `pyproject.toml` and runs it on every PR
through the `types` job in `.github/workflows/ci.yml`. The job is currently
**advisory** — errors appear in the PR check list but don't block merges.
This document explains why, where the current count stands, and how to
contribute to bringing it down.

## Why advisory, not blocking

The codebase passed through several iterative phases (the orchestrator graph,
the MCP HITL state machine, the JWT verifier, the observability handlers)
where the shape of the upstream library types was still settling. Locking
strict mypy as a merge gate in that period would have produced one of two
outcomes:

- Every PR carrying a "fix mypy ignore" pre-task, slowing real work
- Liberal `# type: ignore` annotations that hide real type errors

Neither is the right shape for production code. Instead the project's
typing posture is: strict-by-config, advisory-by-CI. Errors are visible on
every PR. Merge gating turns on when the count is low enough that fixing
on the way past a function is faster than ignoring it.

## Current count

As of v0.17.0: **54 errors across 20 files**.

The largest categories:

| Category | Approx count | Typical fix |
|---|---|---|
| Missing type args on generics (`BaseCheckpointSaver`, etc.) | ~15 | Add `[Any]` or proper TypeVar |
| Unused `# type: ignore` | ~10 | Delete the comment |
| Library overload mismatches (langgraph `ainvoke`) | ~8 | Often library-shape drift; pin a type alias |
| Function-level no-untyped-def | ~6 | Add return annotation |
| Other | ~15 | Case-by-case |

## How to contribute

1. Run `mypy cascade/` locally; open the file with the easiest error to fix.
2. Fix one error. Don't add `# type: ignore` unless the error is a verified
   library bug or a known LangGraph generic limitation — and if so, leave a
   comment naming the upstream issue.
3. Verify the fix didn't regress runtime behaviour: `pytest --no-cov` against
   the affected module.
4. Open a one-line PR. Small PRs land quickly; large mypy-cleanup PRs stall
   on review.

## When the gate flips

The `continue-on-error: true` flag comes off the `types` job when the
error count is **under 10**. At that point a new contributor adding a
fresh error is fixing a specific thing, not paying the accumulated tax of
the codebase's history. CHANGELOG will note the transition under the
release that ships it.
