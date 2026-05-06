"""OKR detail view — single OKR with KRs, score breakdown, and decision trail."""

from __future__ import annotations

from typing import TYPE_CHECKING
from uuid import UUID

import streamlit as st

from cascade.ui.api_client import APIError
from cascade.ui.views.components import (
    format_iso_datetime,
    score_indicator,
    status_badge,
)

if TYPE_CHECKING:
    from cascade.ui.api_client import APIClient


def render(client: APIClient, *, objective_id: UUID) -> None:
    """Render the detail view for a single OKR."""
    try:
        okr = client.get_okr(objective_id)
    except APIError as exc:
        if exc.status_code == 404:
            st.error("This OKR no longer exists. It may have been abandoned.")
            return
        _render_api_error(exc)
        return

    # --- header --------------------------------------------------------------

    st.header(okr["title"])
    if okr.get("description"):
        st.caption(okr["description"])

    cols = st.columns([1, 1, 1, 2])
    cols[0].markdown(f"**Quarter**\n\n{okr['quarter']}")
    cols[1].markdown(f"**Status**\n\n{status_badge(okr['status'])}")
    cols[2].markdown(f"**Score**\n\n{score_indicator(okr['score'])}")
    cols[3].caption(
        f"Created {format_iso_datetime(okr['created_at'])} • "
        f"Updated {format_iso_datetime(okr['updated_at'])}"
    )

    if okr.get("parent_objective_id"):
        st.markdown(f"↑ **Parent:** `{okr['parent_objective_id'][:8]}`")

    # --- key results ---------------------------------------------------------

    st.subheader("Key Results")
    if not okr["key_results"]:
        st.info("No key results on this OKR.")
    for kr in okr["key_results"]:
        with st.container(border=True):
            cols = st.columns([5, 2, 2])
            cols[0].markdown(f"**{kr['description']}**")
            cols[1].markdown(status_badge(kr["status"]))
            cols[2].markdown(score_indicator(kr["score"]))

            sub = st.columns(4)
            sub[0].metric("Baseline", _fmt_value(kr))
            sub[1].metric("Current", _fmt_value(kr, field="current_value"))
            sub[2].metric("Target", _fmt_value(kr, field="target_value"))
            sub[3].metric("Weight", f"{kr['weight']:.2f}")

    # --- decision trail ------------------------------------------------------

    st.subheader("Decision trail")
    st.caption(
        "Every state-changing event captured with the alternatives considered "
        "and the tradeoff accepted."
    )

    try:
        decisions_body = client.list_okr_decisions(objective_id, limit=50)
    except APIError as exc:
        _render_api_error(exc)
        return

    decisions = decisions_body.get("items", [])
    if not decisions:
        st.info("No decisions recorded for this OKR yet.")
        return

    for decision in decisions:
        _render_decision(decision)


def _render_decision(decision: dict) -> None:  # type: ignore[type-arg]
    event_type = decision["event_type"].replace("_", " ").title()
    summary = decision["summary"]
    created = format_iso_datetime(decision["created_at"])

    with st.expander(f"**{event_type}** — {summary}  ·  *{created}*"):
        st.markdown(f"**Chose:** {decision['chosen']}")
        if decision.get("tradeoff"):
            st.markdown(f"**Tradeoff:** {decision['tradeoff']}")

        if decision.get("alternatives"):
            st.markdown("**Alternatives considered:**")
            for alt in decision["alternatives"]:
                option = alt.get("option", "")
                rejected_for = alt.get("reason_rejected", "")
                st.markdown(f"- _{option}_ — rejected because {rejected_for}")

        if decision.get("evidence"):
            st.markdown("**Evidence:**")
            for ev in decision["evidence"]:
                source = ev.get("source", "")
                claim = ev.get("claim", "")
                link = ev.get("link", "")
                if link:
                    st.markdown(f"- [{source}]({link}) — {claim}")
                else:
                    st.markdown(f"- {source} — {claim}")


def _fmt_value(kr: dict, *, field: str = "baseline_value") -> str:  # type: ignore[type-arg]
    value = kr.get(field, 0)
    unit = kr.get("unit") or ""
    metric_type = kr.get("metric_type", "number")
    if metric_type == "percentage":
        return f"{value}%"
    if metric_type == "currency":
        return f"${value:,.0f}"
    if unit:
        return f"{value:,.0f} {unit}"
    return f"{value:,.0f}"


def _render_api_error(exc: APIError) -> None:
    if exc.status_code == 401:
        st.error("Authentication failed.")
    elif exc.status_code == 0:
        st.error(f"Could not reach the API: {exc.detail}")
    else:
        st.error(f"API error {exc.status_code}: {exc.detail}")


__all__ = ["render"]
