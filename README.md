# cascade

> Most OKR tools track *what* you committed to. cascade also remembers *why* — every target, target change, and reframe is captured as a structured Decision with the alternatives considered and the tradeoff accepted, so the reasoning survives quarters, reorgs, and turnover.

<p>
  <a href="https://github.com/Akash-1512/cascade/actions/workflows/ci.yml"><img alt="CI" src="https://github.com/Akash-1512/cascade/actions/workflows/ci.yml/badge.svg"></a>
  <a href="LICENSE"><img alt="License: MIT" src="https://img.shields.io/badge/License-MIT-blue.svg"></a>
  <img alt="Python 3.12+" src="https://img.shields.io/badge/python-3.12+-blue.svg">
  <img alt="Tests: 275 passing" src="https://img.shields.io/badge/tests-275%20passing-brightgreen">
  <img alt="MCP: 8 tools" src="https://img.shields.io/badge/MCP-8%20tools-blueviolet">
</p>

cascade is an OKR governance platform with multi-agent AI coaching and an
organizational memory layer designed to outlive the people who built it. It
exposes its capabilities over the **Model Context Protocol** so the same data
is queryable from Claude Desktop, Cursor, or any MCP-aware client.

```bash
python -m cascade.mcp.server   # 8 tools available in Claude Desktop in 3 lines of config
```

## What makes it different

Three concrete capabilities that off-the-shelf OKR tools don't ship:

1. **Six-agent coaching loop** — a Drafter / Critic / Aligner / Coach / Reflector / Risk Sentinel ensemble built on LangGraph. The Critic gates drafts on measurability, ambition, specificity, and structure with deterministic verdict normalisation; the Aligner detects vertical drift and horizontal conflicts before commit.
2. **Causal memory layer** — every state-changing event becomes a typed Decision row with alternatives, tradeoff, and evidence. Conversational memory uses a hybrid retrieval pipeline (BM25 + dense + cross-encoder rerank); causal memory is queryable through the `query_decisions` MCP tool months later.
3. **Eval gate in CI** — 30 hand-labeled OKR drafts, 10 retrieval cases, 6 adversarial attack types. Threshold floors live in `eval_data/thresholds.yaml`; loosening one requires an ADR.

## Architecture at a glance

```
                      ┌──────────────────────────────┐
   intent  ──────────▶│   LangGraph state machine    │
                      │                              │
                      │    Drafter ⇄ Critic → Aligner│ ─── HITL escalation
                      └──────────┬───────────────────┘
                                 │
                                 ▼
                      ┌──────────────────────┐
                      │    MemoryRecorder    │
                      └──────┬───────┬───────┘
                             │       │
                             ▼       ▼
            ┌─────────────────┐   ┌──────────────────────┐
            │   Postgres      │   │   ChromaDB           │
            │  (causal memory │   │  (conversational     │
            │   + OKR state)  │   │   memory + vectors)  │
            └─────────────────┘   └──────────────────────┘
                       ▲                     ▲
                       │                     │
                       └─── HybridRetriever ─┘
                            (BM25 + dense + rerank)
                                    ▲
                                    │
                            ContextBuilder
                            (per-agent budgets)
                                    ▲
                                    │
                              MCP server
                              (8 tools)
                                    ▲
                                    │
                          Claude Desktop / Cursor
```

Six agents, three storage tiers, one orchestrator. See
[`docs/architecture/overview.md`](docs/architecture/overview.md) for the long
version and [`docs/adr/`](docs/adr/) for the design decisions.

## Quick start

```bash
git clone https://github.com/Akash-1512/cascade.git
cd cascade

# Bring up Postgres and ChromaDB
docker compose up -d

# Install with dev extras
pip install -e ".[dev]"

# Run migrations
alembic upgrade head

# Run the test suite
pytest                      # 275 tests, ~5 seconds
pytest -m unit              # unit only
pytest --cov=cascade        # with coverage

# Run the eval gate
python -m cascade.evals.gate --use-fakes --output eval_results.json
python -m cascade.evals.check_thresholds eval_results.json

# Start the MCP server
python -m cascade.mcp.server                            # stdio
python -m cascade.mcp.server --transport sse            # SSE
python -m cascade.mcp.server --transport streamable-http
```

## Use it from Claude Desktop

Add to `claude_desktop_config.json`:

```json
{
  "mcpServers": {
    "cascade": {
      "command": "python",
      "args": ["-m", "cascade.mcp.server"],
      "env": {
        "DATABASE_URL": "postgresql+psycopg://cascade:cascade@localhost:5432/cascade",
        "GROQ_API_KEY": "your-key-here"
      }
    }
  }
}
```

Restart Claude Desktop. The eight cascade tools become available:

| Tool | Purpose |
|---|---|
| `list_okrs` | Compact summaries by team and quarter |
| `get_okr` | Full Objective view with KRs and derived scores |
| `draft_okr` | Drafter + Critic loop returning a proposal and verdict |
| `score_okr` | Current score breakdown for an existing Objective |
| `log_checkin` | Coach-mediated check-in with structured persistence |
| `query_decisions` | Causal trail for an Objective |
| `assess_risk` | Risk Sentinel agent with intervention recommendations |
| `get_alignment` | Aligner agent with vertical and horizontal checks |

Full configuration and examples in
[`docs/runbooks/mcp-server.md`](docs/runbooks/mcp-server.md).

## What lives where

```
cascade/
├── agents/         Six agents: drafter, critic, aligner, checkin_coach,
│                   reflector, risk_sentinel — plus shared contracts and prompts
├── domain/         Pydantic v2 models — OKR, KeyResult, Decision, CheckIn
├── storage/        SQLAlchemy 2.0 + Alembic; repositories for each aggregate
├── memory/         3-tier memory: protocols, BM25, hybrid retrieval, ChromaDB
│                   store, dynamic context builder, decision recorder
├── orchestrator/   LangGraph state machine + deterministic supervisor
├── mcp/            8-tool MCP server (FastMCP)
└── evals/          Drafting, retrieval, red-team eval gate

docs/
├── architecture/   Overview, agents, memory, evals, observability
├── adr/            ADR-0001 LangGraph, ADR-0002 causal memory,
│                   ADR-0003 dynamic context construction
└── runbooks/       MCP server, eval gate

eval_data/          30 golden OKR drafts, 10 retrieval cases,
                    6 red-team attacks, threshold floors

tests/
├── unit/           244 unit tests
├── integration/    31 integration tests (PG + ChromaDB)
└── e2e/            live smoke tests (skip without GROQ_API_KEY)
```

## Stack

| Layer | Choice | Why |
|---|---|---|
| Agent orchestration | LangGraph | Deterministic supervisor; type-safe state; ADR-0001 |
| Agent contracts | Pydantic v2 | `extra="forbid"`, structured outputs, plays well with FastMCP |
| LLM provider | Groq (LLaMA 3.3 70B) + OpenAI fallback | Free tier for dev, cheap routing in prod |
| Causal memory | Postgres + JSONB | Relational queries on alternatives and tradeoffs; ADR-0002 |
| Conversational memory | ChromaDB | In-process ONNX MiniLM, no PyTorch dependency |
| Retrieval | BM25 + dense + LLM cross-encoder rerank | Each catches what the others miss; ADR-0003 |
| Persistence | SQLAlchemy 2.0 async + Alembic | Async sessions, repository pattern, migration history |
| MCP server | FastMCP | Auto-derives JSON schemas from Pydantic types |
| Tests | pytest + pytest-asyncio | 275 tests in ~5 seconds with SQLite override |
| Eval gate | Custom Pydantic-typed harness | Drafting F1 + retrieval F1 + red-team pass rate |
| CI | GitHub Actions | Lint, types, unit, integration, build, eval, security |

## Status

Pre-release. v0.7.0 ships with the eval gate and the MCP surface. See
[CHANGELOG.md](CHANGELOG.md) for the full release history and the roadmap
to v1.0.

## Documentation

- [Architecture overview](docs/architecture/overview.md) — how the pieces fit
- [Agent design](docs/architecture/agents.md) — what each of the six agents does
- [Memory layer](docs/architecture/memory.md) — three tiers and the hybrid retriever
- [Eval gate](docs/architecture/evals.md) — what the gate measures and why
- [Observability](docs/architecture/observability.md) — LangSmith tracing pattern
- [ADRs](docs/adr/) — decisions and the alternatives considered
- [MCP server runbook](docs/runbooks/mcp-server.md) — client configuration
- [Eval gate runbook](docs/runbooks/eval-gate.md) — running and adding cases
- [Contributing](CONTRIBUTING.md)
- [Security policy](SECURITY.md)

## License

MIT — see [LICENSE](LICENSE).
