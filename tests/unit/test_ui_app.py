"""App-level tests using Streamlit's :class:`AppTest`.

These exercise the full app — sidebar rendering, view dispatch, error
handling — with the API client patched to return canned responses. No real
HTTP and no real Streamlit server runs.

These are slower than unit tests (each AppTest run starts a fresh script),
so we keep them focused on flows that components-level tests can't cover.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock
from uuid import uuid4

import pytest
from streamlit.testing.v1 import AppTest

from cascade.ui import api_client as api_client_module


def _make_okr(**overrides: Any) -> dict[str, Any]:
    okr_id = overrides.pop("id", str(uuid4()))
    return {
        "id": okr_id,
        "title": overrides.get("title", "Reach product-market fit in the SMB segment"),
        "description": overrides.get("description"),
        "quarter": overrides.get("quarter", "2026Q2"),
        "status": overrides.get("status", "active"),
        "team_id": overrides.get("team_id", str(uuid4())),
        "owner_id": str(uuid4()),
        "parent_objective_id": None,
        "score": overrides.get("score", 0.5),
        "key_results": overrides.get(
            "key_results",
            [
                {
                    "id": str(uuid4()),
                    "description": "Lift weekly active accounts from 200 to 800",
                    "metric_type": "number",
                    "baseline_value": 200,
                    "target_value": 800,
                    "current_value": 500,
                    "unit": "accounts",
                    "weight": 1.0,
                    "status": "on_track",
                    "score": 0.5,
                }
            ],
        ),
        "created_at": "2026-04-01T00:00:00",
        "updated_at": "2026-05-06T00:00:00",
    }


def _patch_api_client(monkeypatch: pytest.MonkeyPatch, **canned: Any) -> MagicMock:
    """Replace APIClient.from_env so the app gets a mock with canned methods."""
    mock_client = MagicMock(spec=api_client_module.APIClient)
    mock_client.health.return_value = canned.get(
        "health", {"status": "ok", "version": "0.10.0", "cascade_env": "development"}
    )
    mock_client.list_team_okrs.return_value = canned.get(
        "list_team_okrs", {"items": [], "count": 0}
    )
    mock_client.get_okr.return_value = canned.get("get_okr", _make_okr())
    mock_client.list_okr_decisions.return_value = canned.get(
        "list_okr_decisions", {"items": [], "count": 0}
    )
    mock_client.list_team_learnings.return_value = canned.get(
        "list_team_learnings", {"items": [], "count": 0}
    )

    def _from_env(*, bearer_token: str, transport: Any = None) -> MagicMock:
        return mock_client

    monkeypatch.setattr(api_client_module.APIClient, "from_env", _from_env)
    # Also patch via the import path the app uses
    monkeypatch.setattr("cascade.ui.app.APIClient.from_env", _from_env)
    return mock_client


@pytest.mark.unit
def test_app_loads_with_no_token_shows_warning(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """With no bearer token configured, the app warns the user."""
    _patch_api_client(monkeypatch)
    at = AppTest.from_file("cascade/ui/app.py")
    at.run(timeout=10)
    assert not at.exception
    warnings_text = " ".join(w.value for w in at.warning)
    assert "bearer token" in warnings_text.lower()


@pytest.mark.unit
def test_app_with_token_but_no_team_id_prompts(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Bearer token set but no team — prompt for one rather than 500ing."""
    _patch_api_client(monkeypatch)
    at = AppTest.from_file("cascade/ui/app.py")
    at.session_state["bearer_token"] = str(uuid4())
    at.run(timeout=10)
    assert not at.exception
    info_messages = " ".join(i.value for i in at.info)
    assert "team" in info_messages.lower()


@pytest.mark.unit
def test_okr_list_view_renders_with_data(monkeypatch: pytest.MonkeyPatch) -> None:
    """When the API returns OKRs, the list view shows them."""
    okr = _make_okr(title="Reach PMF in SMB this quarter")
    mock_client = _patch_api_client(
        monkeypatch,
        list_team_okrs={"items": [okr], "count": 1},
    )

    at = AppTest.from_file("cascade/ui/app.py")
    at.session_state["bearer_token"] = str(uuid4())
    at.session_state["team_id_input"] = str(uuid4())
    at.session_state["view"] = "OKR list"
    at.run(timeout=10)
    assert not at.exception

    # The list view should have called the API with the team id and quarter.
    mock_client.list_team_okrs.assert_called_once()
    # The found-count message is rendered.
    rendered = " ".join(m.value for m in at.markdown)
    assert "1" in rendered


@pytest.mark.unit
def test_okr_list_empty_state_renders_info(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_api_client(monkeypatch)  # default returns empty list
    at = AppTest.from_file("cascade/ui/app.py")
    at.session_state["bearer_token"] = str(uuid4())
    at.session_state["team_id_input"] = str(uuid4())
    at.session_state["view"] = "OKR list"
    at.run(timeout=10)
    assert not at.exception
    info_messages = " ".join(i.value for i in at.info)
    assert "no okrs" in info_messages.lower()


@pytest.mark.unit
def test_invalid_team_id_uuid_shows_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_api_client(monkeypatch)
    at = AppTest.from_file("cascade/ui/app.py")
    at.session_state["bearer_token"] = str(uuid4())
    at.session_state["team_id_input"] = "not-a-uuid"
    at.run(timeout=10)
    assert not at.exception
    errors_text = " ".join(e.value for e in at.error)
    assert "not a valid uuid" in errors_text.lower()


@pytest.mark.unit
def test_learnings_view_renders_themes(monkeypatch: pytest.MonkeyPatch) -> None:
    learning = {
        "id": str(uuid4()),
        "team_id": str(uuid4()),
        "quarter": "2026Q2",
        "title": "Underestimated dependency on data team",
        "description": "Three OKRs slipped on instrumentation timing in Q2.",
        "category": "estimation",
        "occurrences": 3,
        "affected_okr_ids": [],
        "supersedes_id": None,
        "created_at": "2026-04-01T00:00:00",
    }
    _patch_api_client(
        monkeypatch,
        list_team_learnings={"items": [learning], "count": 1},
    )

    at = AppTest.from_file("cascade/ui/app.py")
    at.session_state["bearer_token"] = str(uuid4())
    at.session_state["team_id_input"] = str(uuid4())
    at.session_state["view"] = "Learnings"
    at.run(timeout=10)
    assert not at.exception
    rendered = " ".join(m.value for m in at.markdown)
    assert "Underestimated dependency" in rendered


@pytest.mark.unit
def test_okr_detail_renders_with_kr_metrics(monkeypatch: pytest.MonkeyPatch) -> None:
    """The detail view should call get_okr and render the KR's score metric."""
    okr_id = str(uuid4())
    okr = _make_okr(id=okr_id)
    _patch_api_client(monkeypatch, get_okr=okr)

    at = AppTest.from_file("cascade/ui/app.py")
    at.session_state["bearer_token"] = str(uuid4())
    at.session_state["team_id_input"] = str(uuid4())
    at.session_state["selected_okr_id"] = okr_id
    at.session_state["view"] = "OKR detail"
    at.run(timeout=10)
    assert not at.exception
    # The KR description is rendered as markdown
    rendered = " ".join(m.value for m in at.markdown)
    assert "Lift weekly active accounts" in rendered
