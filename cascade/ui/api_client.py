"""Thin HTTP client for the cascade REST API.

Intentionally framework-agnostic — knows nothing about Streamlit. The UI
imports this and calls plain functions; tests use ``httpx.MockTransport``
to stub responses without standing up a real server.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any
from uuid import UUID

import httpx

DEFAULT_API_URL = "http://localhost:8000"
DEFAULT_TIMEOUT_SECONDS = 10.0


class APIError(Exception):
    """Raised when the API returns a non-2xx response."""

    def __init__(self, status_code: int, detail: str) -> None:
        super().__init__(f"{status_code}: {detail}")
        self.status_code = status_code
        self.detail = detail


@dataclass(frozen=True, slots=True)
class APIClient:
    """Read-only client for the cascade REST API.

    Construct once per session; keep the underlying ``httpx.Client`` alive
    across requests for connection reuse.
    """

    base_url: str
    bearer_token: str
    _client: httpx.Client

    @classmethod
    def from_env(
        cls,
        *,
        bearer_token: str,
        transport: httpx.BaseTransport | None = None,
    ) -> APIClient:
        """Build a client using environment configuration.

        ``CASCADE_UI_API_URL`` overrides the default base URL. Pass
        ``transport`` for testing — :class:`httpx.MockTransport` is the easy
        path to stubbing the network.
        """
        base_url = os.environ.get("CASCADE_UI_API_URL", DEFAULT_API_URL).rstrip("/")
        client = httpx.Client(
            base_url=base_url,
            timeout=DEFAULT_TIMEOUT_SECONDS,
            transport=transport,
        )
        return cls(base_url=base_url, bearer_token=bearer_token, _client=client)

    def close(self) -> None:
        self._client.close()

    # -- health -------------------------------------------------------------

    def health(self) -> dict[str, Any]:
        return self._get("/health", auth=False)

    def readiness(self) -> dict[str, Any]:
        return self._get("/health/ready", auth=False)

    # -- okrs ---------------------------------------------------------------

    def list_team_okrs(self, team_id: UUID, *, quarter: str | None = None) -> dict[str, Any]:
        """Return the OKR summary list for a team, optionally filtered by quarter."""
        params: dict[str, str] = {}
        if quarter is not None:
            params["quarter"] = quarter
        return self._get(f"/v1/teams/{team_id}/okrs", params=params)

    def get_okr(self, objective_id: UUID) -> dict[str, Any]:
        """Return the full OKR view including KRs and derived scores."""
        return self._get(f"/v1/okrs/{objective_id}")

    def get_okr_score(self, objective_id: UUID) -> dict[str, Any]:
        """Return the per-KR scoring breakdown for an OKR."""
        return self._get(f"/v1/okrs/{objective_id}/score")

    def list_okr_decisions(self, objective_id: UUID, *, limit: int = 50) -> dict[str, Any]:
        """Return the causal trail for an OKR, newest first."""
        return self._get(f"/v1/okrs/{objective_id}/decisions", params={"limit": str(limit)})

    # -- learnings ----------------------------------------------------------

    def list_team_learnings(
        self,
        team_id: UUID,
        *,
        quarter: str | None = None,
        category: str | None = None,
        limit: int = 100,
    ) -> dict[str, Any]:
        """Return organizational learning themes for a team."""
        params: dict[str, str] = {"limit": str(limit)}
        if quarter is not None:
            params["quarter"] = quarter
        if category is not None:
            params["category"] = category
        return self._get(f"/v1/teams/{team_id}/learnings", params=params)

    # -- internals ----------------------------------------------------------

    def _get(
        self,
        path: str,
        *,
        params: dict[str, str] | None = None,
        auth: bool = True,
    ) -> dict[str, Any]:
        headers = {"Authorization": f"Bearer {self.bearer_token}"} if auth else {}
        try:
            response = self._client.get(path, params=params, headers=headers)
        except httpx.RequestError as exc:
            raise APIError(0, f"Network error: {exc}") from exc

        if response.status_code >= 400:
            try:
                detail = response.json().get("detail", response.text)
            except ValueError:
                detail = response.text
            raise APIError(response.status_code, detail)

        return response.json()


__all__ = ["DEFAULT_API_URL", "APIClient", "APIError"]
