# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [0.11.0] - 2026-05-06

### Added
- **Demo seed script** so a reviewer cloning the repo sees populated content
  end-to-end on first run. Seeds one team (slug `demo-team`), two users,
  three OKRs across two quarters, eight decisions, and three organizational
  learnings.
- `make demo` and `make demo-reset` Makefile targets — idempotent first
  run, explicit refresh on `--reset`. The script prints the team UUID for
  pasting into the operator console sidebar.
- `python -m cascade.scripts.seed_demo [--reset] [--verbose]` CLI for direct
  invocation.
- `cascade/scripts/demo_data.py` — plain-Python data classes defining the
  seed content. Reviewers reading the demo data are reading what cascade is
  *for* (real OKR titles, alternatives-considered decisions, recurring-
  pattern learnings).
- `cascade/scripts/seed_demo.py` — idempotent orchestrator. Slug-based team
  lookup; first run creates everything; second run skips with a one-line
  message; `--reset` wipes the demo team's rows (scoped strictly to its
  team_id, never touches non-demo data) and re-seeds.
- `cascade/scripts/README.md` per-component README documenting CLI
  options, the idempotency contract, and the why-declared-as-data choice.

### Changed
- Top-level README quick-start now leads with `make demo` so the first
  command after `pip install` produces a populated console.
- Test-count badge and stack-table line updated from 275 to 349 (will be
  365 after this release ships).
- Operator console runbook replaces the manual `psql INSERT` example with
  a pointer to `make demo`.
- Makefile gets `demo` and `demo-reset` targets; `.PHONY` updated.

### Tests
- 365 total: 282 unit + 82 integration (all green); 1 e2e skipped without keys
- 8 new unit tests for demo data referential integrity (every decision actor
  resolves to a seeded user, every decision objective_title resolves to a
  seeded OKR, KR weights sum to 1.0 per OKR, learning quarters match the
  YYYYQ[1-4] format, decisions have alternatives or evidence, count
  stability)
- 8 new integration tests for the seed orchestrator (first-run counts, slug
  lookup, decision references no orphans, double-run skip idempotency,
  reset refresh keeps counts stable, reset preserves non-demo data, content
  is real not Lorem ipsum)

### Design choices documented
- Slug-based team identifier (`demo-team`) rather than a hardcoded UUID —
  human-readable and stable across runs.
- Wipe scoped strictly to the demo team's id — running `--reset` against a
  database with non-demo teams is safe; the test
  `test_reset_does_not_touch_non_demo_data` guards this.
- Demo data declared as plain dataclasses rather than algorithmically
  generated — generated content looks like a benchmark, not like a real
  team. Keeping the OKRs, decisions, and learnings written in human voice
  makes them useful as a reading aid.

## [0.10.0] - 2026-05-06

### Added
- **Streamlit operator console** as the third integration surface alongside
  the MCP server and REST API. Read-only viewer for OKRs, KRs, decision
  trails, and organizational learnings.
- Three views:
  - **OKR list** — sortable table with status badges and score indicators;
    drill-down picker into the detail view
  - **OKR detail** — full single-OKR view with KR metrics (baseline,
    current, target, weight) and the complete decision trail with
    alternatives, tradeoffs, and evidence
  - **Learnings** — quarterly themes filterable by category, with
    supersedes-link rendering for resolved themes
- `cascade.ui.api_client.APIClient` — thin synchronous httpx wrapper that
  surfaces a single typed `APIError` so views handle one exception type
  rather than catching httpx exceptions directly. Tests use
  `httpx.MockTransport` to stub responses without standing up a server.
- `cascade.ui.views.components` — shared visual vocabulary (status badges
  with semantic colour mapping, score indicators with thresholds matching
  the Risk Sentinel, category badges, ISO datetime formatting that
  tolerates Z suffixes, current-and-recent quarters helper)
- Sidebar configuration for API URL, bearer token, team ID, quarter, and
  view selection. Connection-status panel runs `/health` on every render.
- `cascade/ui/README.md` per-component README and
  `docs/runbooks/operator-console.md` runbook
- New `ui` extra in `pyproject.toml` (`pip install -e ".[ui]"`) — keeps
  Streamlit and pandas out of the API/core install

### Changed
- Top-level README now lists three integration surfaces side-by-side
  (MCP, REST, console) with short usage examples

### Tests
- 349 total: 280 unit + 68 integration (all green); 1 e2e skipped without keys
- 11 new unit tests for the API client (auth header presence, query params,
  error mapping, network failure wrapping, malformed error body fallback)
- 12 new unit tests for shared components (status thresholds, score colour
  thresholds, datetime formatting edge cases, quarter helpers monotonic)
- 7 new Streamlit `AppTest` tests covering sidebar prompts, view dispatch,
  empty states, and error paths with the API client patched

### Design choices documented
- Console is read-only — drafts/commits/check-ins flow through the MCP
  server because that's where the agent loop lives. A second mutation path
  in the UI would skip the Critic, the Aligner, and the Decision recorder.
- Single typed `APIError` for all client failures (network + 4xx + 5xx)
  rather than leaking httpx exceptions to views
- Unknown statuses fall back to a grey badge rather than raising —
  forward-compatible with API additions
- Three-tier test pyramid for the UI: pure components → mocked client →
  full app via `AppTest`. Keeps coverage broad without making the test
  suite slow.

## [0.9.0] - 2026-05-06

### Added
- **REST API** as the second integration surface alongside the MCP server.
  Read-side projection over OKRs, decisions, and organizational learnings;
  mutations stay in MCP because that's where the agent loop lives.
- Routes:
  - `GET /v1/teams/{team_id}/okrs?quarter={q}` — list OKRs, optionally
    filtered by quarter
  - `GET /v1/okrs/{id}` — full OKR view with KRs and derived scores
  - `GET /v1/okrs/{id}/score` — per-KR scoring breakdown
  - `GET /v1/okrs/{id}/decisions?limit={n}` — causal trail
  - `GET /v1/teams/{team_id}/learnings?quarter={q}&category={c}` —
    organizational learnings, filterable by quarter or category
- Health and readiness probes:
  - `GET /health` — liveness, no external dependencies (returns 200 even
    during DB outages so K8s doesn't kill the pod)
  - `GET /health/ready` — readiness, verifies Postgres is reachable
- JWT bearer auth scaffolding (`cascade.api.auth`) with two modes:
  - `dev` — accepts any UUID as the principal's `user_id`, useful for
    curl, the upcoming Streamlit operator console, and local development
  - `jwt` — production placeholder; fails closed (503) until a real JWKS
    verifier is wired in
- `Principal` dataclass, `require_principal` FastAPI dependency, and
  `SessionDep` for database-backed routes
- Wire schemas in `cascade.api.schemas` distinct from `cascade.mcp.schemas`
  so the two surfaces evolve independently
- CORS middleware configured via `CASCADE_API_CORS_ALLOW_ORIGINS`
- `cascade/api/README.md` per-component README documenting routes,
  auth modes, the read-only design choice, and curl examples
- `docs/runbooks/rest-api.md` runbook with full curl examples and
  troubleshooting

### Changed
- Top-level README now lists both integration surfaces (MCP and REST) with
  short usage examples
- `tests/conftest.py` `api_client` fixture monkeypatches `get_sessionmaker`
  so unit tests don't require psycopg
- `Settings` gains `api_auth_mode` and `api_cors_allow_origins`

### Tests
- 319 total: 250 unit + 68 integration (all green); 1 e2e skipped without keys
- 5 new unit tests for the auth dependency (missing token → 401, dev-mode
  UUID acceptance, dev-mode non-UUID rejection, JWT-mode unconfigured 503,
  Principal frozen)
- 13 new integration tests covering all routes and auth paths

## [0.8.0] - 2026-05-06

### Added
- **HITL resumption** — the orchestrator graph now supports human-in-the-loop
  resumption via LangGraph's `interrupt()` primitive. When the graph reaches
  the `human` node with a checkpointer attached, it pauses with state
  durable in the checkpointer; the caller resumes with
  `Command(resume={"decision": "...", "notes": "..."})` and the graph
  re-routes through the supervisor.
- Three resumption decisions: `commit` (force aligned, demote blocking
  conflicts to info, complete the run), `revise` (clear proposal/critique/
  alignment, send back to Drafter), `abandon` (force blocked with audit
  conflict, terminate).
- `cascade.orchestrator.resumption` module with `apply_resume_payload`
  (called inside the human node) and `resume()` (caller convenience
  wrapper).
- `build_graph` accepts an optional `checkpointer`. Without one, the human
  node falls back to the previous "set `awaiting_human` and end" behaviour
  for backwards compatibility.
- **OrganizationalLearning persistence** — durable storage for Reflector
  themes so quarterly retrospectives accumulate across quarters rather than
  evaporating. Themes are immutable and append-only; `supersedes_id` carries
  the audit trail.
- `cascade.domain.organizational_learning` with `OrganizationalLearning`
  and `OrganizationalLearningCreate` Pydantic types
- `cascade.storage.repositories.organizational_learning.OrganizationalLearningRepository`
  with `create`, `list_for_team` (filter by quarter or category), and `get`
- New ORM table `organizational_learnings` with FK cascade to teams,
  category enum check, quarter regex check (Postgres-only; SQLite skips it),
  and team+quarter and category indexes
- Alembic migration `0002_organizational_learnings`
- `cascade.agents.reflector_persistence.persist_reflection_themes` bridges
  Reflector output to durable storage; only persists themes with
  `occurrences >= 2` (single-instance themes are anecdotes, not patterns)

### Changed
- `tests/integration/conftest.py` strips Postgres regex CHECK constraints
  for SQLite test runs — production deployments still get the regex
  enforcement; tests trade that for portability
- ORM model test list updated to include the new `organizational_learnings`
  table

### Tests
- 301 total: 244 unit + 57 integration (all green); 1 e2e skipped without keys
- 9 new unit tests for resume payload application
- 6 new integration tests for the HITL resumption path through the real
  AsyncSqliteSaver checkpointer
- 6 new integration tests for OrganizationalLearningRepository
- 5 new integration tests for `persist_reflection_themes`

## [0.7.1] - 2026-05-06

### Documentation
- Top-level README rewritten for first-impression density. Leads with the
  causal-memory differentiator, ASCII architecture diagram showing all six
  agents and three storage tiers, quick-start commands, Claude Desktop config
  block, full eight-tool table, repo layout, and stack rationale table.
- Per-component README files for the four major subsystems:
  `cascade/agents/README.md`, `cascade/memory/README.md`,
  `cascade/mcp/README.md`, `cascade/evals/README.md`. Each documents purpose,
  files, key design decisions, and testing surface.
- CONTRIBUTING.md updated with the eval-gate workflow, accurate test
  commands, the threshold-loosening process, and pointers to per-component
  READMEs.
- Architecture overview updated to reflect what's actually built: MCP server
  as the primary surface, three eval families with thresholds, ChromaDB's
  default ONNX MiniLM (no PyTorch), OpenAI as the fallback provider.

This is a documentation-only release. No source code, behaviour, or test
changes — 275 tests still pass, lint and format clean.

## [0.7.0] - 2026-05-06

### Added
- **Eval gate** — three eval families gating merges in CI. Threshold floors live
  in `eval_data/thresholds.yaml`; loosening one requires an ADR.
  - `drafting_f1` — Critic verdict agreement on a 30-case golden dataset
    (10 pass / 10 needs_revision / 10 reject across 9 functional roles).
    Threshold 0.85.
  - `retrieval_f1` — Hybrid retrieval F1 on 10 memory-question cases with
    self-contained corpora. Threshold 0.90.
  - `red_team_pass_rate` — Adversarial robustness across 6 attack types
    (vague injection, sandbagging, target gaming, prompt injection,
    decision laundering, memory poisoning). Threshold 0.95.
- `cascade.evals.gate` — runner that produces a structured `EvalReport`. Exits 0
  even on metric failure so the report is uploadable as a CI artifact regardless.
- `cascade.evals.check_thresholds` — separate gate step that exits non-zero on
  regression and lists the top 5 failing case ids per breached metric.
- `--use-fakes` mode for plumbing smoke tests without consuming Groq quota.
- `--filter` and `--case-id` for narrow targeted runs.
- Eval-gate runbook in `docs/runbooks/eval-gate.md` covering dataset structure,
  failure modes, and how to add new cases or eval families.
- Three datasets shipped: `eval_data/golden_okrs.jsonl`,
  `eval_data/memory_questions.jsonl`, `eval_data/red_team_attacks.jsonl`.

### Changed
- `eval-gate.yml` workflow: falls back to `--use-fakes` when `GROQ_API_KEY` is
  missing so the harness itself can be smoke-tested even without secrets
  configured. Threshold check only runs when a real key is configured.

### Tests
- 275 total: 244 unit + 31 integration (all green); 1 e2e skipped without keys
- 32 new tests: 11 dataset, 13 eval-module, 8 runner/threshold-checker

## [0.6.0] - 2026-05-05

### Added
- **MCP server** — cascade is now queryable over the Model Context Protocol from
  Claude Desktop, Cursor, or any MCP-compatible client. Built on FastMCP with
  auto-derived JSON schemas from Pydantic types.
- Eight MCP tools registered:
  - `list_okrs` — compact OKR summaries filtered by team and quarter
  - `get_okr` — full Objective view with KRs and derived scores
  - `draft_okr` — Drafter + Critic loop with verdict
  - `score_okr` — current score breakdown for an existing Objective
  - `log_checkin` — Coach-mediated check-in with structured persistence
  - `query_decisions` — causal trail for an Objective
  - `assess_risk` — Risk Sentinel agent with intervention recommendations
  - `get_alignment` — Aligner agent with vertical and horizontal checks
- Wire-format schemas in `cascade.mcp.schemas` distinct from `cascade.domain` so
  the protocol surface evolves independently of the persistence schema
- Adapters in `cascade.mcp.adapters` for clean conversion between domain and wire
  types — UUIDs as strings, datetimes as ISO 8601, Pydantic→dict for nested
  alternatives and evidence
- Three transport modes: stdio (Claude Desktop / Cursor), SSE, streamable-http
- `cascade-mcp` console script and `python -m cascade.mcp.server` entry point
- MCP runbook with Claude Desktop and Cursor configuration examples
- README updated with MCP advertisement and transport options

### Tests
- 243 total: 209 unit + 34 integration (all green); 1 e2e skipped without keys
- 13 new tests: 10 adapter unit + 9 MCP integration + 3 server entry-point unit

## [0.5.0] - 2026-05-05

### Added
- **Aligner agent** — vertical and horizontal alignment checks. Vertical score in
  [0, 1] against a parent OKR; horizontal conflict detection (resource, metric,
  scope, timing) against peer OKRs. Verdict normalisation makes the gate
  deterministic regardless of LLM variance: any blocking conflict OR vertical < 0.4
  forces blocked; any warning conflict OR vertical < 0.7 forces needs_review.
- **Check-in Coach agent** — turns free-text owner messages into structured
  updates. Forces `requires_confirmation` whenever a target value changes so the
  HITL interrupt always fires for target-change decisions.
- **Reflector agent** — quarterly retrospective. Groups check-ins by their owning
  OKR via KR id resolution; groups decisions by objective_id; renders a structured
  prompt the LLM clusters into themes (with category enum), wins, losses, and
  specific recommendations.
- **Risk Sentinel agent** — velocity-based at-risk prediction. Score normalised
  against `INTERVENTION_THRESHOLD = 0.5`; stalled velocity overrides the threshold
  regardless of score so a flatlined OKR always gets attention.
- Per-agent prompt templates: `aligner.j2`, `checkin_coach.j2`, `reflector.j2`,
  `risk_sentinel.j2`
- Aligner integrated into the LangGraph state machine — Drafter → Critic → Aligner
  with HITL escalation on alignment_conflict
- Extended `OKRState` with `peer_objectives`, `alignment`, `risk` fields
- Extended `HumanInterrupt` reasons with `alignment_conflict` and `kr_descope`

### Tests
- 221 total: 196 unit + 25 integration (all green); 1 e2e skipped without keys
- 24 new unit tests across the four new agents
- Supervisor and graph tests updated for the new aligner routing

## [0.4.0] - 2026-05-05

### Added
- Memory layer protocols: `Embedder`, `Reranker`, `Retriever`, `MemoryStore` —
  swappable implementations without touching agent code
- `BM25Index` — keyword index for high-precision retrieval on rare terms,
  named entities, and project codenames
- `HybridRetriever` — three-stage pipeline (BM25 + dense + cross-encoder rerank)
  unifying lexical and semantic signals
- `LLMReranker` — cross-encoder pattern via the chat model, with neutral-score
  fallback when scoring fails
- `ChromaMemoryStore` — production-grade vector store using ChromaDB's default
  ONNX MiniLM embeddings (no PyTorch dependency)
- In-memory fakes (`HashEmbedder`, `IdentityReranker`, `InMemoryStore`,
  `StaticRetriever`) for hermetic unit tests
- `ContextBuilder` — dynamic task-aware prompt assembly with per-agent retrieval
  budgets; replaces static-context-file pattern
- `MemoryRecorder` — bridges agent runs to durable storage; persists Objective →
  Decision → transcript chunks in the right order with cross-references
- ADR-0003 documenting the dynamic-context design rationale

### Changed
- Drafter accepts an optional `context_builder` plus `okr_id`, `team_id`, and
  `quarter` for memory-aware revisions; the prompt template renders a "Relevant
  memory" section when context is provided
- Drafter prompt template extended with a memory_context block

### Tests
- 193 total: 168 unit + 25 integration (all green); 1 e2e skipped without keys

## [0.3.0] - 2026-05-05

### Added
- LangGraph state machine with deterministic Supervisor router
- **Drafter agent** — converts strategic intent into well-formed proposed Objectives
  with 2–5 measurable Key Results, with iteration history awareness for revision loops
- **Critic agent** — scores proposals on four dimensions (specificity, measurability,
  ambition, structure), detects vague language, returns structured verdicts
- Drafter↔Critic loop with `ITERATION_CAP=3` and HITL escalation on cap or reject
- Verdict normalisation — overrides LLM "pass" verdict when any dimension is below
  threshold, making the gate deterministic regardless of model variance
- Groq (LLaMA 3.3 70B) primary with retry; Together AI optional fallback via
  OpenAI-compatible endpoint
- Jinja2 prompt template loader with StrictUndefined and a `nice_num` filter for
  clean number rendering; templates live in `cascade/agents/prompts/*.j2`
- `FakeChatModel` for hermetic agent tests with deterministic response sequences
- Live smoke test in `tests/e2e/` that runs against real Groq when `GROQ_API_KEY` is
  set; skipped otherwise

### Tests
- 159 total: 134 unit + 25 integration (all green) + 1 e2e skipped without keys

## [0.2.0] - 2026-05-05

### Added
- Pydantic v2 domain models: `Objective`, `KeyResult`, `Decision`, `CheckIn`, `User`,
  `Team`, `Quarter`, with type-safe enums for status, metric type, and decision events
- Pure scoring functions (`score_linear`, `score_boolean`, `score_milestone`,
  `score_key_result`, `score_objective`) with deterministic semantics for increasing,
  decreasing, and "maintain X" KRs
- SQLAlchemy 2.0 ORM models for the seven domain tables with named constraints,
  cascading foreign keys, and indexes for the highest-volume query paths
- Async session factory and `get_session` FastAPI dependency
- Repository pattern for `Team`, `Objective`, and `Decision` aggregates
- Alembic migration `0001_initial_schema` creating all tables and Postgres enum types
- Integration test fixtures supporting both SQLite (default, fast) and Postgres
  (via `CASCADE_TEST_DATABASE_URL`)
- 120 tests total: 97 unit + 23 integration, all green

### Changed
- CI integration-tests job now exports `CASCADE_TEST_DATABASE_URL` so the suite runs
  against the Postgres service container

## [0.1.0] - 2026-05-05

### Added
- Initial repository scaffolding
- MIT license
- Project README and contribution guidelines
- Python project metadata (`pyproject.toml`)
- Ruff and pre-commit configuration
- GitHub Actions CI skeleton
- Docker development stack
- Architecture documentation skeleton

[Unreleased]: https://github.com/Akash-1512/cascade/compare/v0.11.0...HEAD
[0.11.0]: https://github.com/Akash-1512/cascade/compare/v0.10.0...v0.11.0
[0.10.0]: https://github.com/Akash-1512/cascade/compare/v0.9.0...v0.10.0
[0.9.0]: https://github.com/Akash-1512/cascade/compare/v0.8.0...v0.9.0
[0.8.0]: https://github.com/Akash-1512/cascade/compare/v0.7.1...v0.8.0
[0.7.1]: https://github.com/Akash-1512/cascade/compare/v0.7.0...v0.7.1
[0.7.0]: https://github.com/Akash-1512/cascade/compare/v0.6.0...v0.7.0
[0.6.0]: https://github.com/Akash-1512/cascade/compare/v0.5.0...v0.6.0
[0.5.0]: https://github.com/Akash-1512/cascade/compare/v0.4.0...v0.5.0
[0.4.0]: https://github.com/Akash-1512/cascade/compare/v0.3.0...v0.4.0
[0.3.0]: https://github.com/Akash-1512/cascade/compare/v0.2.0...v0.3.0
[0.2.0]: https://github.com/Akash-1512/cascade/compare/v0.1.0...v0.2.0
[0.1.0]: https://github.com/Akash-1512/cascade/releases/tag/v0.1.0
