# cascade.observability

Tracing, cost tracking, and eval telemetry — three integrations, all
opt-in via environment variables. When none are configured, every
public function is a no-op.

## Files

```
observability/
├── __init__.py          Re-exports
├── handlers.py          ObservabilityState + build_callback_handlers
└── mlflow_runner.py     mlflow_run context + log_metrics / log_params
```

## Surface

```python
from cascade.observability import (
    build_callback_handlers,    # list of LangChain callbacks; empty when nothing configured
    observability_state,        # ObservabilityState describing what's active
    mlflow_run,                 # context manager that wraps an MLflow run when configured
    log_metrics,                # log a flat dict to the active MLflow run; no-op outside one
    log_params,                 # same, for run params
)
```

## How callers wire it

`cascade.agents.llm.get_chat_model()` calls `build_callback_handlers()`
and attaches the result to the model. LangSmith activates via env-var
detection inside LangChain itself — that's why the returned list never
includes a LangSmith handler (would double-trace).

`cascade.evals.gate.run_evals()` wraps its body in
`mlflow_run("eval-gate-{timestamp}")` and calls `log_metrics` /
`log_params` after the eval body runs. With MLflow unconfigured this is
a transparent pass-through; with MLflow configured every run is one
experiment row.

## Why three integrations

Different teams pick different stacks. The MCP server, REST API, and
eval gate don't care which is configured — they all wire through the
same factory and runner. Adding a fourth (Phoenix, Helicone, etc.)
would mean adding a branch in `_build_*` and updating the runbook;
nothing else needs to change.

## Why fail-quiet

A trace is a debugging artifact, not a load-bearing component. If
LangSmith is down, the agent loop must still produce a draft. If MLflow
is unreachable, the eval gate must still produce a report. Every
integration in this module catches construction failures, swallows
mid-run errors, and logs at WARNING/ERROR — never raises out to the
caller.

## Tests

- `tests/unit/test_observability_handlers.py` — 14 tests covering
  state inspection, build_callback_handlers branching, package-missing
  degradation, construction-failure degradation
- `tests/unit/test_observability_mlflow.py` — 11 tests covering
  context manager (URI not set, package missing, both error paths),
  log_metrics (NaN/inf filtering, error swallowing), log_params
  (string coercion, no-op outside run)
- `tests/integration/test_observability_eval_gate.py` — 2 tests
  verifying run_evals logs the right metric and param shapes when
  MLflow is configured, and runs unchanged when it isn't

The fakes inject a stub `mlflow` or `langfuse` module into `sys.modules`
so the tests exercise the real branching logic without needing the
optional packages installed.

## Setup

See `docs/runbooks/observability.md` for env-var configuration,
expected trace shapes, and troubleshooting.
