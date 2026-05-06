"""Tests for :class:`cascade.ui.api_client.APIClient`."""

from __future__ import annotations

from uuid import uuid4

import httpx
import pytest

from cascade.ui.api_client import APIClient, APIError


def _client_with_handler(handler) -> APIClient:  # type: ignore[no-untyped-def]
    transport = httpx.MockTransport(handler)
    return APIClient.from_env(bearer_token=str(uuid4()), transport=transport)


@pytest.mark.unit
def test_health_does_not_send_bearer_token() -> None:
    """Liveness is a public probe — sending an Authorization header would
    couple the UI's auth state to a check that's meant to work even when
    the user is logged out."""
    captured: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        captured.append(request)
        return httpx.Response(200, json={"status": "ok", "version": "x", "cascade_env": "dev"})

    client = _client_with_handler(handler)
    body = client.health()
    assert body["status"] == "ok"
    assert "Authorization" not in captured[0].headers


@pytest.mark.unit
def test_list_team_okrs_attaches_bearer_token() -> None:
    captured: list[httpx.Request] = []
    team_id = uuid4()

    def handler(request: httpx.Request) -> httpx.Response:
        captured.append(request)
        assert request.url.path == f"/v1/teams/{team_id}/okrs"
        return httpx.Response(200, json={"items": [], "count": 0})

    client = _client_with_handler(handler)
    client.list_team_okrs(team_id)

    assert captured[0].headers["Authorization"].startswith("Bearer ")


@pytest.mark.unit
def test_list_team_okrs_passes_quarter_filter() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.params.get("quarter") == "2026Q2"
        return httpx.Response(200, json={"items": [], "count": 0})

    client = _client_with_handler(handler)
    client.list_team_okrs(uuid4(), quarter="2026Q2")


@pytest.mark.unit
def test_list_team_okrs_omits_quarter_when_not_set() -> None:
    """When the caller doesn't pass a quarter, no query parameter is sent —
    let the API return the default rather than asserting a specific one."""

    def handler(request: httpx.Request) -> httpx.Response:
        assert "quarter" not in request.url.params
        return httpx.Response(200, json={"items": [], "count": 0})

    client = _client_with_handler(handler)
    client.list_team_okrs(uuid4())


@pytest.mark.unit
def test_get_okr_returns_parsed_body() -> None:
    okr_id = uuid4()
    body = {
        "id": str(okr_id),
        "title": "Reach PMF in SMB",
        "description": None,
        "quarter": "2026Q2",
        "status": "active",
        "team_id": str(uuid4()),
        "owner_id": str(uuid4()),
        "parent_objective_id": None,
        "score": 0.5,
        "key_results": [],
        "created_at": "2026-04-01T00:00:00",
        "updated_at": "2026-05-06T00:00:00",
    }

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=body)

    client = _client_with_handler(handler)
    result = client.get_okr(okr_id)
    assert result["title"] == "Reach PMF in SMB"
    assert result["score"] == 0.5


@pytest.mark.unit
def test_404_raises_api_error_with_status_and_detail() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(404, json={"detail": "Objective not found"})

    client = _client_with_handler(handler)
    with pytest.raises(APIError) as exc_info:
        client.get_okr(uuid4())
    assert exc_info.value.status_code == 404
    assert "not found" in exc_info.value.detail


@pytest.mark.unit
def test_401_raises_api_error() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(401, json={"detail": "Missing Authorization header"})

    client = _client_with_handler(handler)
    with pytest.raises(APIError) as exc_info:
        client.get_okr(uuid4())
    assert exc_info.value.status_code == 401


@pytest.mark.unit
def test_network_error_wrapped_in_api_error() -> None:
    """A connection failure becomes an APIError with status 0 — the UI handles
    a single error type rather than catching httpx exceptions directly."""

    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection refused")

    client = _client_with_handler(handler)
    with pytest.raises(APIError) as exc_info:
        client.get_okr(uuid4())
    assert exc_info.value.status_code == 0
    assert "Network error" in exc_info.value.detail


@pytest.mark.unit
def test_list_decisions_passes_limit() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.params.get("limit") == "25"
        return httpx.Response(200, json={"items": [], "count": 0})

    client = _client_with_handler(handler)
    client.list_okr_decisions(uuid4(), limit=25)


@pytest.mark.unit
def test_list_learnings_passes_filters() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.params.get("quarter") == "2026Q2"
        assert request.url.params.get("category") == "estimation"
        return httpx.Response(200, json={"items": [], "count": 0})

    client = _client_with_handler(handler)
    client.list_team_learnings(uuid4(), quarter="2026Q2", category="estimation")


@pytest.mark.unit
def test_malformed_error_body_falls_back_to_text() -> None:
    """When the API returns a non-JSON error body, the client uses the raw text
    rather than choking. Real-world: 502 from a load balancer."""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(502, content=b"<html>bad gateway</html>")

    client = _client_with_handler(handler)
    with pytest.raises(APIError) as exc_info:
        client.get_okr(uuid4())
    assert exc_info.value.status_code == 502
    assert "bad gateway" in exc_info.value.detail.lower()
