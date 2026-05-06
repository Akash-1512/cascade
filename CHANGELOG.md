# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

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

[Unreleased]: https://github.com/Akash-1512/cascade/compare/v0.7.1...HEAD
[0.7.1]: https://github.com/Akash-1512/cascade/compare/v0.7.0...v0.7.1
[0.7.0]: https://github.com/Akash-1512/cascade/compare/v0.6.0...v0.7.0
[0.6.0]: https://github.com/Akash-1512/cascade/compare/v0.5.0...v0.6.0
[0.5.0]: https://github.com/Akash-1512/cascade/compare/v0.4.0...v0.5.0
[0.4.0]: https://github.com/Akash-1512/cascade/compare/v0.3.0...v0.4.0
[0.3.0]: https://github.com/Akash-1512/cascade/compare/v0.2.0...v0.3.0
[0.2.0]: https://github.com/Akash-1512/cascade/compare/v0.1.0...v0.2.0
[0.1.0]: https://github.com/Akash-1512/cascade/releases/tag/v0.1.0
