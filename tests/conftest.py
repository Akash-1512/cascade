"""Shared pytest fixtures for cascade tests."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def api_client(monkeypatch: pytest.MonkeyPatch) -> Iterator[TestClient]:
    """A FastAPI test client whose lifespan and readiness check don't require Postgres.

    Used by unit tests that just want to exercise routing, OpenAPI generation,
    and the health endpoints. Integration tests use their own ``api_client``
    fixture in :mod:`tests.integration.test_api_routes` that wires a real
    SQLite-backed session.
    """
    fake_session = AsyncMock()
    fake_session.execute = AsyncMock(return_value=None)

    @asynccontextmanager
    async def fake_sessionmaker_call():  # type: ignore[no-untyped-def]
        yield fake_session

    fake_sessionmaker = MagicMock(side_effect=lambda: fake_sessionmaker_call())

    # Patch get_sessionmaker before the FastAPI lifespan runs so the real
    # implementation (which imports psycopg) never executes in unit tests.
    monkeypatch.setattr("cascade.api.main.get_sessionmaker", lambda: fake_sessionmaker)

    # Import the app after the patch is in place.
    from cascade.api.main import app

    with TestClient(app) as client:
        yield client
