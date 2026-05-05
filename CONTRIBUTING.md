# Contributing to cascade

Thanks for your interest. This document covers the workflow, conventions, and quality bar
expected from contributions.

## Development setup

Requirements: Python 3.12+, Docker, Docker Compose, GNU Make (optional).

```bash
git clone https://github.com/Akash-1512/cascade.git
cd cascade

python -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -e ".[dev,evals]"

pre-commit install
docker compose up -d postgres chromadb

cp .env.example .env               # fill in keys before running agents
pytest -m unit                     # confirm setup
```

## Branching model

We use a lightweight GitHub Flow with a long-lived `develop` integration branch.

- `main` — protected. Only release tags merge here.
- `develop` — protected. Default base for feature branches.
- `feature/<short-slug>` — new functionality
- `fix/<short-slug>` — bug fixes
- `chore/<short-slug>` — tooling, refactors, non-functional
- `docs/<short-slug>` — documentation only

Open PRs against `develop`. Releases are cut by merging `develop` into `main` and tagging.

## Commit messages

We follow [Conventional Commits](https://www.conventionalcommits.org/en/v1.0.0/).

```
<type>(<scope>): <short summary>

<body — optional, what and why>

<footer — optional, breaking changes, issue refs>
```

Allowed types: `feat`, `fix`, `chore`, `docs`, `refactor`, `perf`, `test`, `build`, `ci`.

Scopes typically map to subsystems: `agents`, `memory`, `mcp`, `api`, `evals`, `obs`,
`domain`, `ci`, `docker`.

## Pull request checklist

Before requesting review, confirm:

- [ ] Branch is rebased on latest `develop`
- [ ] `ruff check .` passes
- [ ] `ruff format --check .` passes
- [ ] `mypy cascade/` passes
- [ ] `pytest -m "not slow"` passes locally
- [ ] New code has tests; coverage on touched files is at least 85%
- [ ] If touching the agent graph or eval suite: eval gate still passes
- [ ] Public API changes are reflected in `docs/`
- [ ] CHANGELOG entry added under `[Unreleased]`

## Code style

- Type hints everywhere — `mypy --strict` enforces this on `cascade/`.
- Pydantic v2 models for all boundary data (API, MCP tools, agent state).
- No bare `except:` — catch the narrowest exception that fits.
- Logs via `structlog`, never `print()`. `cli.py` is the only exception.
- Keep agent prompts in `cascade/agents/prompts/` as `.j2` templates, not Python strings.

## Architecture decisions

Significant architectural choices are recorded as ADRs in `docs/adr/`. If you propose a
change that affects more than one subsystem or alters the public contract, open an ADR
in the same PR.

Format: see `docs/adr/0000-template.md`.

## Security

Do not open public issues for security reports. See [SECURITY.md](SECURITY.md).
