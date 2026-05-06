# Architecture overview

cascade is a Python service that helps teams run OKRs well. It has four cooperating
subsystems and one shared substrate.

```
                    ┌──────────────────────────────────────────────────┐
                    │                   Clients                        │
                    │  Streamlit UI    REST API    MCP (Claude/Cursor) │
                    └──────────────────────────────────────────────────┘
                                          │
                    ┌─────────────────────┼─────────────────────┐
                    ▼                     ▼                     ▼
              ┌──────────┐         ┌────────────┐         ┌──────────┐
              │   API    │         │ MCP Server │         │   UI     │
              │ FastAPI  │         │  FastMCP   │         │Streamlit │
              └──────────┘         └────────────┘         └──────────┘
                    │                     │                     │
                    └─────────┬───────────┘                     │
                              ▼                                 │
                    ┌──────────────────────┐                    │
                    │  Agent Orchestrator  │◄───────────────────┘
                    │   (LangGraph)        │
                    │                      │
                    │  Drafter   Critic    │
                    │  Aligner   Coach     │
                    │  Reflector Risk      │
                    └──────────────────────┘
                              │
                    ┌─────────┴──────────┐
                    ▼                    ▼
              ┌──────────┐         ┌──────────────┐
              │ Memory   │         │ Observability│
              │          │         │              │
              │ Causal   │         │ LangSmith    │
              │ Conv.    │         │ Langfuse     │
              │ Org      │         │ MLflow       │
              └──────────┘         └──────────────┘
                    │
              ┌─────┴──────┐
              ▼            ▼
        ┌──────────┐  ┌─────────┐
        │ Postgres │  │ChromaDB │
        └──────────┘  └─────────┘
```

## Subsystems

### 1. Agent orchestrator (`cascade/orchestrator`, `cascade/agents`)

A LangGraph state machine that routes requests to specialised agents. The graph holds
shared state (the OKR being worked on, the conversation history, the user context, the
retrieved memories) and a Supervisor node decides which agent runs next.

Six agents:

- **Drafter** — turns intent into a well-formed Objective + KRs
- **Critic** — scores drafts against measurability, ambition, alignment heuristics
- **Aligner** — checks vertical and horizontal alignment via GraphRAG over the OKR tree
- **Check-in Coach** — runs progress conversations, extracts blockers and decisions
- **Reflector** — quarterly retros, pushes patterns into organizational memory
- **Risk Sentinel** — velocity-based at-risk prediction with HITL intervention review

Human-in-the-loop interrupts at three points: OKR commit, target reduction, risk
intervention.

See [agents.md](./agents.md) for per-agent contracts.

### 2. Memory layer (`cascade/memory`)

Three storage tiers serving different retrieval needs:

- **Decision graph** — Postgres tables capturing every state-changing event with
  alternatives considered and tradeoffs accepted. Structured, not free text.
- **Conversational memory** — ChromaDB collection of check-in and drafting transcripts.
- **Organizational knowledge** — hybrid retrieval (BM25 + dense + cross-encoder rerank)
  that surfaces *why* in natural language.

The `ContextBuilder` performs dynamic, task-aware prompt assembly — different prompts for
different agents, retrieved from memory rather than dumped as a single static block.

See [memory.md](./memory.md) for schemas and retrieval flows.

### 3. Integration surfaces (`cascade/mcp`)

**MCP server** is the primary integration surface. Eight tools are exposed via
FastMCP with auto-derived JSON schemas from Pydantic types. Three transports
supported: stdio (Claude Desktop / Cursor), SSE (cross-process), and
streamable-http (production behind a reverse proxy).

REST API and Streamlit UI are planned for future phases. The MCP surface
covers the read paths an operator console would need today, and the gap
between an MCP client like Claude Desktop and a custom UI is shrinking.

### 4. Evals & observability (`cascade/evals`, `cascade/observability`)

Quality is enforced, not aspired to. CI gates merges on three eval families:

- **drafting_f1** — Critic verdict agreement on a 30-case hand-labeled golden
  set (10 pass / 10 needs_revision / 10 reject across 9 functional roles).
  Threshold 0.85.
- **retrieval_f1** — Hybrid retrieval F1 on 10 self-contained memory-question
  cases. Threshold 0.90.
- **red_team_pass_rate** — Adversarial robustness across 6 attack types
  (vague injection, sandbagging, target gaming, prompt injection, decision
  laundering, memory poisoning). Threshold 0.95.

Threshold floors live in `eval_data/thresholds.yaml`; loosening one requires
an ADR. Two-step gating: the runner produces a structured `EvalReport`
(always uploaded as artifact); the threshold checker reads it and exits
non-zero on regression.

Traces flow to LangSmith. Costs and latency to Langfuse. Eval runs and
prompt versions to MLflow.

See [evals.md](./evals.md) and [observability.md](./observability.md).

## Substrate

- **Postgres 16** — system of record for OKRs, KRs, check-ins, decisions, users
- **ChromaDB** — vector store for conversational memory; default embedding
  function is ONNX MiniLM (no PyTorch dependency)
- **Groq (LLaMA 3.3 70B)** — primary LLM, free tier
- **OpenAI** — fallback provider when Groq is rate-limited
- **LLM cross-encoder** — reranking via the chat model itself; ONNX
  cross-encoder model is a drop-in replacement at scale

## Deployment topology

A single Docker Compose stack runs the full system locally. Production deployments
typically split:

- API + MCP server behind a reverse proxy (1+ replicas)
- A shared Postgres
- A managed vector store or a dedicated ChromaDB instance
- Observability is SaaS for all three stacks

See [deployment/](../deployment/) for reference manifests.

## What this isn't

- Not a replacement for a planning tool (no Gantt charts, no resource allocation)
- Not an HR or performance management system (no calibration, no comp linkage)
- Not a chatbot wrapper around an OKR table — agents are stateful and accountable

These boundaries are deliberate. See `docs/adr/0002-product-scope.md`.
