"""cascade operator console — Streamlit entry point.

Run with::

    streamlit run cascade/ui/app.py

The sidebar carries the configuration (API URL, bearer token, team id) and
view selection. Each view module renders against an APIClient, so the
configuration plumbing is concentrated here and views stay testable.
"""

from __future__ import annotations

import os
from uuid import UUID

import streamlit as st

from cascade.ui.api_client import APIClient, APIError
from cascade.ui.views import learnings as learnings_view, okr_detail, okr_list
from cascade.ui.views.components import current_and_recent_quarters

st.set_page_config(
    page_title="cascade operator console",
    page_icon="🎯",
    layout="wide",
)


def _init_session_state() -> None:
    """Seed Streamlit session state on first load."""
    defaults: dict[str, object] = {
        "api_url": os.environ.get("CASCADE_UI_API_URL", "http://localhost:8000"),
        "bearer_token": os.environ.get("CASCADE_UI_BEARER_TOKEN", ""),
        "team_id_input": "",
        "view": "OKR list",
        "selected_okr_id": None,
        "selected_quarter": "All",
    }
    for key, value in defaults.items():
        if key not in st.session_state:
            st.session_state[key] = value


def _render_sidebar() -> tuple[APIClient | None, UUID | None, str | None]:
    """Render the sidebar; return ``(client, team_id, quarter)`` or Nones if not yet configured."""
    with st.sidebar:
        st.title("cascade")
        st.caption("OKR governance with multi-agent AI coaching")

        st.divider()
        st.subheader("Connection")
        st.session_state["api_url"] = st.text_input(
            "API URL",
            value=st.session_state["api_url"],
            help="The cascade REST API base URL.",
        )
        st.session_state["bearer_token"] = st.text_input(
            "Bearer token",
            value=st.session_state["bearer_token"],
            type="password",
            help=(
                "In dev mode this is any UUID. In production this is the "
                "JWT issued by your identity provider."
            ),
        )

        st.divider()
        st.subheader("Team & quarter")
        st.session_state["team_id_input"] = st.text_input(
            "Team ID (UUID)",
            value=st.session_state["team_id_input"],
        )
        quarter_options = ["All", *current_and_recent_quarters(count=8)]
        st.session_state["selected_quarter"] = st.selectbox(
            "Quarter",
            options=quarter_options,
            index=quarter_options.index(st.session_state["selected_quarter"])
            if st.session_state["selected_quarter"] in quarter_options
            else 0,
        )

        st.divider()
        st.subheader("View")
        st.session_state["view"] = st.radio(
            "Pick a view",
            options=["OKR list", "OKR detail", "Learnings"],
            index=["OKR list", "OKR detail", "Learnings"].index(st.session_state["view"]),
            label_visibility="collapsed",
        )

        st.divider()
        with st.expander("Connection status"):
            _render_health_panel()

    if not st.session_state["bearer_token"]:
        st.warning(
            "Configure the bearer token in the sidebar to load data. In dev mode any UUID works."
        )
        return None, None, None

    os.environ["CASCADE_UI_API_URL"] = st.session_state["api_url"]
    client = APIClient.from_env(bearer_token=st.session_state["bearer_token"])

    team_id: UUID | None = None
    raw_team = st.session_state["team_id_input"].strip()
    if raw_team:
        try:
            team_id = UUID(raw_team)
        except ValueError:
            st.error(f"`{raw_team}` is not a valid UUID — check the team id.")

    quarter = (
        None
        if st.session_state["selected_quarter"] == "All"
        else st.session_state["selected_quarter"]
    )
    return client, team_id, quarter


def _render_health_panel() -> None:
    """Render a small health indicator inside the sidebar."""
    if not st.session_state["bearer_token"]:
        st.caption(":gray-badge[idle]")
        return
    try:
        client = APIClient.from_env(bearer_token=st.session_state["bearer_token"])
        body = client.health()
        st.caption(
            f":green-badge[healthy] · v{body.get('version', '?')} · {body.get('cascade_env', '?')}"
        )
    except APIError as exc:
        if exc.status_code == 0:
            st.caption(":red-badge[unreachable]")
            st.caption(exc.detail)
        else:
            st.caption(f":orange-badge[{exc.status_code}]")


def main() -> None:
    _init_session_state()
    client, team_id, quarter = _render_sidebar()

    if client is None or team_id is None:
        if client is not None and not st.session_state["team_id_input"]:
            st.info("Enter a team ID in the sidebar to load OKRs.")
        return

    view = st.session_state["view"]
    if view == "OKR list":
        okr_list.render(client, team_id=team_id, quarter=quarter)
    elif view == "OKR detail":
        selected = st.session_state.get("selected_okr_id")
        if not selected:
            st.info("Pick an OKR from the list view first, or paste an OKR id below.")
            raw = st.text_input("OKR ID (UUID)")
            if raw:
                try:
                    okr_detail.render(client, objective_id=UUID(raw))
                except ValueError:
                    st.error(f"`{raw}` is not a valid UUID.")
        else:
            okr_detail.render(client, objective_id=UUID(selected))
    elif view == "Learnings":
        learnings_view.render(client, team_id=team_id, quarter=quarter)


if __name__ == "__main__":
    main()
