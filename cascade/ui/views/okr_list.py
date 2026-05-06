"""OKR list view — a sortable table of OKRs for a team."""

from __future__ import annotations

from typing import TYPE_CHECKING
from uuid import UUID

import pandas as pd
import streamlit as st

from cascade.ui.api_client import APIError
from cascade.ui.views.components import score_indicator, status_badge

if TYPE_CHECKING:
    from cascade.ui.api_client import APIClient


def render(client: APIClient, *, team_id: UUID, quarter: str | None) -> None:
    """Render the OKR list for a team.

    Args:
        client: API client.
        team_id: Team UUID.
        quarter: Optional quarter filter (e.g. ``"2026Q2"``); ``None`` lists
            all quarters.
    """
    st.header("OKRs")
    if quarter:
        st.caption(f"Showing OKRs for **{quarter}**.")
    else:
        st.caption("Showing OKRs across all quarters.")

    try:
        body = client.list_team_okrs(team_id, quarter=quarter)
    except APIError as exc:
        _render_api_error(exc)
        return

    items = body.get("items", [])
    if not items:
        st.info(
            "No OKRs found for this team and quarter. Drafting flows through "
            "the MCP server — try the Drafter from Claude Desktop or Cursor."
        )
        return

    rows = [
        {
            "ID": _short_id(item["id"]),
            "Title": item["title"],
            "Quarter": item["quarter"],
            "Status": status_badge(item["status"]),
            "Score": score_indicator(item["score"]),
            "_full_id": item["id"],
        }
        for item in items
    ]
    df = pd.DataFrame(rows)

    st.write(f"Found **{body['count']}** OKRs.")
    st.dataframe(
        df.drop(columns=["_full_id"]),
        use_container_width=True,
        hide_index=True,
        column_config={
            "Status": st.column_config.TextColumn(width="small"),
            "Score": st.column_config.TextColumn(width="small"),
            "Title": st.column_config.TextColumn(width="large"),
        },
    )

    # Drill-down picker — Streamlit doesn't have native row-click navigation
    # for st.dataframe, so the picker is the second-best surface.
    titles_by_id = {item["id"]: item["title"] for item in items}
    selected_id = st.selectbox(
        "Select an OKR to view in detail",
        options=list(titles_by_id.keys()),
        format_func=lambda oid: f"{_short_id(oid)} — {titles_by_id[oid]}",
        key="okr_picker",
    )
    if st.button("Open detail view", type="primary"):
        st.session_state["selected_okr_id"] = selected_id
        st.session_state["view"] = "OKR detail"
        st.rerun()


def _short_id(uuid_str: str) -> str:
    return uuid_str[:8]


def _render_api_error(exc: APIError) -> None:
    if exc.status_code == 401:
        st.error(
            "Authentication failed. Check that the bearer token in the sidebar "
            "is a valid UUID (or, in production, a valid JWT)."
        )
    elif exc.status_code == 0:
        st.error(
            "Could not reach the API. Is `uvicorn cascade.api.main:app` running "
            f"at the configured URL?\n\n```\n{exc.detail}\n```"
        )
    else:
        st.error(f"API error {exc.status_code}: {exc.detail}")


__all__ = ["render"]
