"""Organizational learnings view — quarterly retrospective themes."""

from __future__ import annotations

from typing import TYPE_CHECKING
from uuid import UUID

import streamlit as st

from cascade.ui.api_client import APIError
from cascade.ui.views.components import category_badge, format_iso_datetime

if TYPE_CHECKING:
    from cascade.ui.api_client import APIClient

CATEGORIES = ["execution", "planning", "alignment", "estimation", "external", "process"]


def render(client: APIClient, *, team_id: UUID, quarter: str | None) -> None:
    """Render the learnings list for a team."""
    st.header("Organizational learnings")
    st.caption(
        "Themes distilled from quarterly retrospectives. Append-only — when a "
        "theme is resolved, a new row supersedes it rather than overwriting "
        "the original. The audit trail is part of the value."
    )

    cat_cols = st.columns([2, 1])
    selected_category = cat_cols[0].selectbox(
        "Filter by category",
        options=["All", *CATEGORIES],
        key="learnings_category",
    )
    limit = cat_cols[1].number_input("Limit", min_value=10, max_value=200, value=100, step=10)

    category = None if selected_category == "All" else selected_category

    try:
        body = client.list_team_learnings(
            team_id, quarter=quarter, category=category, limit=int(limit)
        )
    except APIError as exc:
        if exc.status_code == 0:
            st.error(f"Could not reach the API: {exc.detail}")
        else:
            st.error(f"API error {exc.status_code}: {exc.detail}")
        return

    items = body.get("items", [])
    if not items:
        st.info(
            "No learnings have been distilled for this filter yet. The "
            "Reflector persists themes after a quarterly retrospective; "
            "single-occurrence themes are skipped to keep the signal high."
        )
        return

    st.write(f"Found **{body['count']}** learning themes.")

    for learning in items:
        _render_learning(learning)


def _render_learning(learning: dict) -> None:  # type: ignore[type-arg]
    title = learning["title"]
    category = learning["category"]
    quarter = learning["quarter"]
    occurrences = learning["occurrences"]

    with st.container(border=True):
        cols = st.columns([5, 1, 1, 1])
        cols[0].markdown(f"### {title}")
        cols[1].markdown(category_badge(category))
        cols[2].markdown(f":blue-badge[{quarter}]")
        cols[3].markdown(f":gray-badge[{occurrences}x]")

        st.markdown(learning["description"])

        affected = learning.get("affected_okr_ids") or []
        if affected:
            shortened = [oid[:8] for oid in affected]
            st.caption(f"Affected OKRs: {', '.join(f'`{s}`' for s in shortened)}")

        if learning.get("supersedes_id"):
            st.caption(
                f"Supersedes earlier theme `{learning['supersedes_id'][:8]}` — "
                "the older theme is preserved for audit but considered resolved."
            )

        st.caption(f"Recorded {format_iso_datetime(learning['created_at'])}")


__all__ = ["render"]
