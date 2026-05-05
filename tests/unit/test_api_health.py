"""Tests for the FastAPI health and readiness endpoints."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from cascade import __version__


@pytest.mark.unit
def test_health_returns_ok(api_client: TestClient) -> None:
    """``GET /health`` returns 200 and includes the package version."""
    response = api_client.get("/health")
    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "ok"
    assert payload["version"] == __version__


@pytest.mark.unit
def test_ready_returns_ok(api_client: TestClient) -> None:
    """``GET /health/ready`` returns 200 once the app is ready to serve traffic."""
    response = api_client.get("/health/ready")
    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "ready"


@pytest.mark.unit
def test_openapi_schema_is_served(api_client: TestClient) -> None:
    """OpenAPI schema is available at the configured path."""
    response = api_client.get("/openapi.json")
    assert response.status_code == 200
    schema = response.json()
    assert schema["info"]["title"] == "cascade"
    assert schema["info"]["version"] == __version__
