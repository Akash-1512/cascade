# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

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

[Unreleased]: https://github.com/Akash-1512/cascade/compare/v0.3.0...HEAD
[0.3.0]: https://github.com/Akash-1512/cascade/compare/v0.2.0...v0.3.0
[0.2.0]: https://github.com/Akash-1512/cascade/compare/v0.1.0...v0.2.0
[0.1.0]: https://github.com/Akash-1512/cascade/releases/tag/v0.1.0
