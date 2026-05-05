.PHONY: help install dev lint format type test test-unit test-integration cov clean docker-up docker-down

PYTHON ?= python3.12
VENV   ?= .venv

help:  ## Show available targets
	@grep -E '^[a-zA-Z_-]+:.*?## ' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*?## "}; {printf "  %-20s %s\n", $$1, $$2}'

install:  ## Create venv and install runtime dependencies
	$(PYTHON) -m venv $(VENV)
	$(VENV)/bin/pip install --upgrade pip
	$(VENV)/bin/pip install -e .

dev:  ## Install with dev and eval extras + pre-commit hooks
	$(PYTHON) -m venv $(VENV)
	$(VENV)/bin/pip install --upgrade pip
	$(VENV)/bin/pip install -e ".[dev,evals]"
	$(VENV)/bin/pre-commit install

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
