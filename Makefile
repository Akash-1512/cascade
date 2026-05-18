.PHONY: help install dev evaluate lint format format-check type test test-unit test-integration cov clean docker-up docker-down demo demo-reset

PYTHON ?= python3.12
VENV   ?= .venv

help:  ## Show available targets
	@grep -E '^[a-zA-Z_-]+:.*?## ' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*?## "}; {printf "  %-20s %s\n", $$1, $$2}'

install:  ## Create venv and install runtime dependencies
	$(PYTHON) -m venv $(VENV)
	$(VENV)/bin/pip install --upgrade pip
	$(VENV)/bin/pip install -e .

dev:  ## Install with all extras (dev + evals + ui + observability) and pre-commit hooks
	$(PYTHON) -m venv $(VENV)
	$(VENV)/bin/pip install --upgrade pip
	$(VENV)/bin/pip install -e ".[dev,evals,ui,observability]"
	$(VENV)/bin/pre-commit install || true   # pre-commit is optional for reviewers

evaluate:  ## Reviewer entry point — set up, run lint + tests + eval gate, print summary
	@echo "==> cascade evaluate: setting up and running the full check"
	@$(MAKE) -s dev
	@echo ""
	@echo "==> Lint"
	@$(VENV)/bin/ruff check . && $(VENV)/bin/ruff format --check .
	@echo ""
	@echo "==> Unit tests"
	@$(VENV)/bin/pytest -m unit --no-cov -q
	@echo ""
	@echo "==> Integration tests (SQLite override, no Postgres needed)"
	@$(VENV)/bin/pytest -m integration --no-cov -q
	@echo ""
	@echo "==> Eval gate (with fakes — harness smoke test, no API keys)"
	@$(VENV)/bin/python -m cascade.evals.gate --use-fakes --output /tmp/cascade-eval.json 2>&1 \
		| grep -E "wrote eval report|eval gate" | tail -2 \
		|| true
	@test -s /tmp/cascade-eval.json && echo "    eval harness OK (fakes don't pass thresholds; that's expected)" \
		|| (echo "    eval harness FAILED — no report written"; exit 1)
	@echo ""
	@echo "==> Helm chart structural validation"
	@$(VENV)/bin/python scripts/validate_helm_chart.py
	@echo ""
	@echo "================================================================"
	@echo "  cascade evaluate: PASSED"
	@echo "================================================================"
	@echo "  Next:"
	@echo "    - Read ARCHITECTURE.md  (system walkthrough with diagrams)"
	@echo "    - Read EVALUATION.md    (5 / 30 / 120 minute reviewer paths)"
	@echo "    - make demo             (seed the database, run the console)"
	@echo "================================================================"

lint:  ## Run ruff lint
	$(VENV)/bin/ruff check .

format:  ## Apply ruff format
	$(VENV)/bin/ruff format .

format-check:  ## Verify ruff format without writing
	$(VENV)/bin/ruff format --check .

type:  ## Run mypy strict
	$(VENV)/bin/mypy cascade/

test: test-unit  ## Default test target

test-unit:  ## Run unit tests
	$(VENV)/bin/pytest -m unit

test-integration:  ## Run integration tests (requires postgres + chromadb)
	$(VENV)/bin/pytest -m integration

test-all:  ## Run the full suite
	$(VENV)/bin/pytest

cov:  ## Generate HTML coverage report
	$(VENV)/bin/pytest --cov=cascade --cov-report=html
	@echo "Coverage report: htmlcov/index.html"

clean:  ## Remove caches and build artifacts
	rm -rf build/ dist/ *.egg-info .pytest_cache .ruff_cache .mypy_cache htmlcov coverage.xml .coverage

docker-up:  ## Start the full development stack
	docker compose up -d

docker-down:  ## Stop and remove containers
	docker compose down

docker-logs:  ## Tail logs from all services
	docker compose logs -f

eval:  ## Run the eval suite locally
	$(VENV)/bin/python -m cascade.evals.gate --output eval_results.json

run-api:  ## Run the API in development mode
	$(VENV)/bin/uvicorn cascade.api.main:app --reload --host 0.0.0.0 --port 8000

run-mcp:  ## Run the MCP server
	$(VENV)/bin/python -m cascade.mcp.server

run-ui:  ## Run the Streamlit UI
	$(VENV)/bin/streamlit run cascade/ui/app.py

demo:  ## Seed the demo dataset (idempotent — skips if already seeded)
	$(VENV)/bin/alembic upgrade head
	$(VENV)/bin/python -m cascade.scripts.seed_demo --verbose

demo-reset:  ## Wipe and re-seed the demo dataset
	$(VENV)/bin/alembic upgrade head
	$(VENV)/bin/python -m cascade.scripts.seed_demo --reset --verbose
