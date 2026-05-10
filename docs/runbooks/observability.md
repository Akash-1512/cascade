# Observability

cascade ships with three opt-in observability integrations. Each activates
via environment variables alone — no code changes required, no per-
environment configuration files to edit. When none are configured the
instrumentation is a complete no-op and the host application behaves
exactly as before.

| Integration | What it gives you | Activates on |
|---|---|---|
| **LangSmith** | Trace exploration, prompt versioning, dataset evals | `LANGSMITH_API_KEY` + `LANGSMITH_TRACING=true` |
| **Langfuse** | Trace exploration + cost/latency tracking + prompt management | `LANGFUSE_PUBLIC_KEY` + `LANGFUSE_SECRET_KEY` |
| **MLflow** | Eval-run experiment tracking with metrics + params over time | `MLFLOW_TRACKING_URI` |

Pick whichever combination fits your stack. LangSmith and Langfuse can
both be on simultaneously — they capture overlapping but not identical
data, and the cost is one extra callback per LLM call. MLflow is
orthogonal to both; it tracks eval-gate runs only.

## Setup

### LangSmith

Most teams already on LangChain. Activate by setting two env vars:

```bash
export LANGSMITH_TRACING=true
export LANGSMITH_API_KEY=ls_...
export LANGSMITH_PROJECT=cascade-prod   # optional; defaults to "cascade"
```

LangChain reads these directly — cascade doesn't pass anything explicit.
Restart the MCP server, REST API, or eval gate; spans appear in the
LangSmith UI within seconds.

The activation rule is "tracing flag AND key both present." Either alone
produces no traces — `observability_state()` reports inactive in that
case so you can spot a half-configured setup in startup logs.

### Langfuse

Langfuse is preferred when cost tracking matters — token-pricing tables
ship per-model, so spend per Drafter call (or per HITL flow) is
queryable without manual math.

```bash
export LANGFUSE_PUBLIC_KEY=pk-lf-...
export LANGFUSE_SECRET_KEY=sk-lf-...
export LANGFUSE_HOST=https://cloud.langfuse.com   # default; self-hosted overrides
```

Install the optional dep:

```bash
pip install 'cascade[observability]'   # pulls langfuse + mlflow
```

Cascade constructs a `LangfuseCallbackHandler` and attaches it to the
chat model. If the package isn't installed, the keys are silently
ignored with a WARNING — observability outages must never crash the
host application. The same WARNING fires if Langfuse construction
fails (auth invalid, host unreachable on init).

### MLflow

MLflow tracks the eval gate — every `cascade.evals.gate.run_evals`
invocation runs inside an MLflow run context with metrics (drafting_f1,
retrieval_f1, red_team_pass_rate) and params (thresholds, filters,
model name) logged.

```bash
export MLFLOW_TRACKING_URI=http://mlflow.internal:5000
export CASCADE_MLFLOW_EXPERIMENT=cascade-evals   # default
```

The Settings field is `mlflow_tracking_uri` (default `None`). When
unset the wrapper is a no-op; when set it tries to start a run and
degrades gracefully on failure. The eval gate itself never errors
because of MLflow.

Self-hosting MLflow is straightforward — `mlflow server --host 0.0.0.0
--port 5000` against any backing store works for a single-node setup.
Production deployments typically use S3 + RDS as the artifact and
metadata stores; consult MLflow's docs for the production setup shape.

## What gets traced

### Per agent call

LangSmith and Langfuse capture every chat-model invocation as a span.
That means a single HITL drafting run produces one span per agent in the
graph — Drafter, Critic, Aligner, optionally Coach, optionally Risk
Sentinel, plus any model calls inside the supervisor. The spans nest
under the parent invocation so you can see the full call tree for one
draft.

The eval gate's evaluator agents (the LLM-as-judge in
`evaluate_drafting`) also produce spans, tagged with the case_id so you
can compare runs across model versions.

### Per eval-gate run

Each run logs to MLflow as one experiment run with:

| Field | Source |
|---|---|
| `metric: drafting_f1` | F1 score from the drafting evaluator |
| `metric: retrieval_f1` | F1 score from the retrieval evaluator |
| `metric: red_team_pass_rate` | Pass rate across red-team cases |
| `metric: <name>_passed` | 1.0 if metric ≥ threshold, 0.0 otherwise |
| `param: metric_filter` | Which metrics ran (or "all") |
| `param: case_filter` | Which cases ran (or "all") |
| `param: groq_model` | Model name used |
| `param: drafting_threshold_f1` | Configured threshold for the F1 gate |
| `param: retrieval_threshold_faithfulness` | Configured threshold |
| `param: red_team_threshold_pass_rate` | Configured threshold |
| `tag: cascade.version` | Package version at run time |
| `tag: cascade.surface` | "eval-gate" |

Run names follow `eval-gate-{ISO8601-Z}` so they sort chronologically
in the MLflow UI.

NaN and infinity are filtered before logging — MLflow rejects them
with a noisy WARNING per metric otherwise, which would flood the logs
on a misconfigured evaluator.

## Verifying the wiring

A small script confirms what's active:

```python
from cascade.observability import observability_state
print(observability_state().summary_line())
# observability: LangSmith→cascade, Langfuse, MLflow→http://mlflow:5000
```

The MCP server, REST API, and eval gate all log this line on startup
(at INFO level). Grep for "observability:" in the startup logs to see
the live state.

## Failure modes

All three integrations follow the same fail-quiet contract:

- **Optional package not installed** → WARNING log, integration treated
  as disabled, host runs normally. The WARNING names the install
  command (`pip install 'cascade[observability]'`).
- **Credentials invalid / host unreachable on init** → ERROR log with
  the exception, integration treated as disabled, host runs normally.
- **Backend rejects a metric / param mid-run** → ERROR log, the
  specific call swallowed, the rest of the run continues.

Observability outages must never propagate to the user. A missing
trace is a small loss; a crashed eval gate is a large one.

## Troubleshooting

**Traces not appearing in LangSmith** — check `observability_state()`.
The most common cause is `LANGSMITH_TRACING` defaulting to false in
some deployment environments. Set it explicitly to "true". A second
common cause: the API key is rotated but the env var still has the old
value; LangSmith silently drops traces with a stale key.

**Langfuse handler logged at startup but no traces** — verify
`LANGFUSE_HOST` matches your tenant. Self-hosted instances and EU
cloud have different hosts; the SDK doesn't error on host mismatch,
it just silently drops events.

**MLflow runs visible but no metrics** — MLflow rejects NaN, +inf,
-inf. If your evaluator produced any of those, cascade filtered them
at the boundary; check the eval-gate logs for "Failed to log MLflow
metrics" entries that name what was rejected.

**Cost tracking shows zero in Langfuse** — Langfuse needs the model
name in the trace event to look up pricing. Verify the chat model has
`model_name` set (it does for `ChatGroq` and `ChatOpenAI` by default,
but custom wrappers sometimes drop it).
