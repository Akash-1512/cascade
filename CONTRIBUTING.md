# Contributing to cascade

Thanks for your interest. This document covers the workflow, conventions, and
quality bar for contributions.

## TL;DR

```bash
git clone https://github.com/Akash-1512/cascade.git
cd cascade
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
pre-commit install
docker compose up -d
alembic upgrade head
pytest                                    # 275 tests in ~5 seconds
ruff check . && ruff format --check .
```

## Project layout

Each major component has a README. Read the one for the area you're touching:

- [`cascade/agents/README.md`](cascade/agents/README.md) — six agents, contracts, prompts
- [`cascade/memory/README.md`](cascade/memory/README.md) — three storage tiers, hybrid retrieval
- [`cascade/mcp/README.md`](cascade/mcp/README.md) — eight MCP tools, transports
- [`cascade/evals/README.md`](cascade/evals/README.md) — eval gate, datasets, thresholds

## Development setup

Requirements: Python 3.12+, Docker, Docker Compose.

```bash
git clone https://github.com/Akash-1512/cascade.git
cd cascade

python -m venv .venv
source .venv/bin/activate              # Windows: .venv\Scripts\activate
pip install -e ".[dev]"

pre-commit install
docker compose up -d postgres chromadb

cp .env.example .env                   # fill GROQ_API_KEY before running live agents
alembic upgrade head
pytest -m unit                         # confirm setup
```

## Branching model

GitHub Flow with a long-lived `develop` integration branch.

- `main` — protected. Only release merges with tags.
- `develop` — protected. Default base for feature branches.
- `feature/<slug>` — new functionality
- `fix/<slug>` — bug fixes
- `chore/<slug>` — tooling, refactors, non-functional
- `docs/<slug>` — documentation only

Open PRs against `develop`. Releases cut by merging `develop` into `main` and
tagging `vX.Y.Z`.

## Commit messages

[Conventional Commits](https://www.conventionalcommits.org/en/v1.0.0/).

```
<type>(<scope>): <short summary>

<body — what and why; ASCII only>

<footer — breaking changes, issue refs>
```

Types: `feat`, `fix`, `chore`, `docs`, `refactor`, `perf`, `test`, `build`, `ci`.

Scopes typically map to subsystems: `agents`, `memory`, `mcp`, `evals`,
`orchestrator`, `domain`, `storage`, `ci`, `docker`.

Avoid em-dashes (—) in commit messages — some Git tooling on Windows mangles
the encoding. Use `--` instead.

## Pull request checklist

Before requesting review, confirm:

- [ ] Branch is rebased on latest `develop`
- [ ] `ruff check .` passes
- [ ] `ruff format --check .` passes
- [ ] `pytest --no-cov` passes (`pytest --cov=cascade` for coverage)
- [ ] New code has tests; per-file coverage on touched files is at least 85%
- [ ] If touching `cascade/agents/`, `cascade/memory/`, `cascade/orchestrator/`, or
      `cascade/evals/`: the eval gate still passes
- [ ] CHANGELOG entry added under `[Unreleased]`
- [ ] Public API changes reflected in the relevant per-component README
- [ ] If a new architectural decision was made, an ADR was added to `docs/adr/`

## Running the eval gate

The eval gate is a regression suite gating merges in CI. Run it locally before
opening a PR if you've touched any agent, memory, orchestrator, or eval code.

```bash
# Plumbing smoke test — no API key needed
python -m cascade.evals.gate --use-fakes --output eval_results.json
python -m cascade.evals.check_thresholds eval_results.json

# Full live run (requires GROQ_API_KEY)
python -m cascade.evals.gate --output eval_results.json
python -m cascade.evals.check_thresholds eval_results.json

# Targeted run for a single case
python -m cascade.evals.gate --filter drafting --case-id good-007 --verbose
```

See [`docs/runbooks/eval-gate.md`](docs/runbooks/eval-gate.md) for full details.

## Code style

- **Type hints everywhere.** Public function signatures are annotated.
- **Pydantic v2** for all boundary data (agent contracts, MCP tools, eval
  reports). Use `ConfigDict(extra="forbid")` so malformed inputs fail fast.
- **No bare `except:`.** Catch the narrowest exception that fits.
- **Logs via `logging`** (not `print`) and route to stderr in CLI entry points.
- **Agent prompts** live as Jinja2 `.j2` templates in
  `cascade/agents/prompts/`, never as inline Python strings.
- **PEP 695 type parameters** (`class Foo[T]:`) where applicable. `mypy` is
  configured to accept them.
- **Async by default** for I/O. Storage layer is fully async; agents return
  `Awaitable[X]`.

## Tests

```bash
pytest                            # all tests, no coverage
pytest -m unit                    # unit only (fast)
pytest -m integration             # integration only (DB-backed)
pytest tests/unit/test_critic.py  # one file
pytest --cov=cascade --cov-report=term-missing
```

Test markers configured in `pyproject.toml`:

- `unit` — pure functions and contracts; no DB, no network
- `integration` — exercises the storage layer (SQLite by default,
  Postgres in CI)
- `e2e` — live calls to LLM providers; skipped without `GROQ_API_KEY`

Integration tests use the SQLite override fixture in
`tests/integration/conftest.py` for fast local feedback. CI runs them against
a real Postgres service container.

## Architecture decisions

Significant architectural choices are recorded as ADRs in `docs/adr/`. If you
propose a change that affects more than one subsystem or alters the public
contract, open an ADR in the same PR.

ADRs follow the format in `docs/adr/0000-template.md`. Existing ADRs:

- ADR-0001: LangGraph for agent orchestration
- ADR-0002: Causal memory as structured Postgres rows
- ADR-0003: Dynamic context construction over static context files

## Loosening a threshold

The eval gate's thresholds in `eval_data/thresholds.yaml` are part of the
contract, not implementation details.

To **lower** a threshold:

1. Open an ADR explaining why
2. Reference the ADR in the PR
3. Get explicit approval from a maintainer

To **raise** a threshold: just open a PR. It comes with a two-week grace
period — anyone with an in-flight branch shouldn't be blocked overnight by a
tightening change.

## Security

Do not open public issues for security reports. See [SECURITY.md](SECURITY.md).

## Code of Conduct

See [CODE_OF_CONDUCT.md](CODE_OF_CONDUCT.md). Be excellent to each other.
