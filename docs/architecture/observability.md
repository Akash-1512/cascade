# Observability

Three tools, three responsibilities. None of them duplicate work.

## LangSmith — agent traces

**What:** every LangGraph run is traced. Each agent invocation, each LLM call, each tool
call is a span with timing, inputs, and outputs.

**Why we use it:** debugging multi-agent flows is impossible without these traces.
"Why did Aligner say there was a horizontal conflict?" needs the exact retrieved context
and the exact prompt to answer.

**What's in the project:** `LANGSMITH_PROJECT=cascade`. Sessions are tagged with
`okr_id`, `tenant_id`, and the agent name. PII is scrubbed before send.

**When to look at it:** debugging agent behaviour, post-mortems on bad outputs.

## Langfuse — LLM cost and latency

**What:** every LLM call, with model, tokens, cost, and latency. Aggregated by tenant
and by agent.

**Why we use it:** cost per OKR drafted, per check-in, per retro. Without this we can't
make rational pricing decisions or catch a runaway prompt that 10x'd token usage.

**What's in the project:** Langfuse SDK wraps the Groq client. Costs are computed from
Groq's published rates.

**When to look at it:** monthly cost reviews, latency regressions after a prompt change.

## MLflow — eval runs and prompt registry

**What:** every eval run logged as an MLflow experiment. Every prompt version logged as
a model artifact.

**Why we use it:** when the eval gate fails, we need to compare *exactly* what changed.
MLflow gives us per-metric trends, side-by-side comparisons, and the ability to roll back
a prompt to an earlier version.

**What's in the project:** `MLFLOW_EXPERIMENT=cascade-evals`. Each agent's prompts are
registered in the model registry under `cascade.<agent>.prompt`.

**When to look at it:** before merging a prompt change, after a release to confirm no
regression.

## Structured logging

`structlog` everywhere. Every log line has:

- `trace_id` — same as the LangSmith trace ID
- `okr_id` and `tenant_id` when available
- `agent` when emitted from an agent
- `event` — a stable string identifier we can grep for

In production, logs go to stdout as JSON; ingestion is the operator's choice.

## Metrics

Prometheus endpoint at `/metrics` on the API service. Default metrics:

- `cascade_okrs_total{event}` — OKRs drafted, committed, closed
- `cascade_agent_duration_seconds{agent}` — histogram per agent
- `cascade_memory_retrieval_seconds{stage}` — bm25, dense, rerank
- `cascade_eval_score{metric}` — most recent eval gate scores
- `cascade_hitl_pending` — count of OKRs awaiting human input

## Health checks

- `GET /health` — liveness, returns 200 if the process is alive
- `GET /health/ready` — readiness, checks Postgres and ChromaDB connectivity

## What we don't do

- **No APM agent** — keeps the runtime image small. OpenTelemetry exporters are wired in
  for operators who want one.
- **No proprietary trace format** — everything is OTel-compatible.
- **No PII in traces** — we redact at the agent boundary, not at the sink, so a
  misconfigured sink doesn't leak.
