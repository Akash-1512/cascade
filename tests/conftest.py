"""Shared pytest fixtures for cascade tests."""

from __future__ import annotations

from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient

from cascade.api.main import app


@pytest.fixture
def api_client() -> Iterator[TestClient]:
    """Return a FastAPI test client with the app's lifespan exercised."""
    with TestClient(app) as client:
        yield client
