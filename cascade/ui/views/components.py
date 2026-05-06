"""Shared UI components for the cascade operator console.

Tiny helpers that wrap Streamlit primitives with consistent styling. Kept in
one module so the visual language stays uniform across views.
"""

from __future__ import annotations

from datetime import datetime
from typing import Final

# Status colour mapping — semantic, not aesthetic. Each colour reflects the
# operational meaning of the state, not a brand choice.
STATUS_COLOURS: Final[dict[str, str]] = {
    "draft": "gray",
    "active": "blue",
    "achieved": "green",
    "missed": "red",
    "abandoned": "orange",
    "on_track": "green",
    "at_risk": "orange",
    "off_track": "red",
    "not_started": "gray",
}

CATEGORY_COLOURS: Final[dict[str, str]] = {
    "execution": "blue",
    "planning": "violet",
    "alignment": "green",
    "estimation": "orange",
    "external": "gray",
    "process": "rainbow",
}


def status_badge(status: str) -> str:
    """Return a Streamlit-rendered coloured badge for an OKR or KR status.

    Returns markdown using Streamlit's :badge syntax. Falls back to a plain
    grey pill for unknown statuses rather than raising — the UI should be
    forgiving when the API adds a new status before the UI ships.
    """
    colour = STATUS_COLOURS.get(status, "gray")
    label = status.replace("_", " ").title()
    return f":{colour}-badge[{label}]"


def category_badge(category: str) -> str:
    """Coloured badge for an organizational learning category."""
    colour = CATEGORY_COLOURS.get(category, "gray")
    return f":{colour}-badge[{category.title()}]"


def score_indicator(score: float) -> str:
    """Render a score as a coloured percentage with a semantic threshold.

    Below 0.3 reads as off-track, 0.3 to 0.7 as in-progress, above 0.7 as
    nearly achieved. The thresholds match the Risk Sentinel's interpretation
    so the numbers say the same thing across surfaces.
    """
    pct = round(score * 100)
    if score >= 0.7:
        colour = "green"
    elif score >= 0.3:
        colour = "blue"
    else:
        colour = "red"
    return f":{colour}-badge[{pct}%]"


def format_iso_datetime(value: str | datetime) -> str:
    """Format an ISO-8601 datetime string from the API as a short readable form."""
    if isinstance(value, datetime):
        dt = value
    else:
        # The API returns ISO strings; parse forgiveingly.
        try:
            dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return value
    return dt.strftime("%Y-%m-%d %H:%M")


def current_and_recent_quarters(*, count: int = 6) -> list[str]:
    """Return the current quarter and the previous ``count - 1`` as labels.

    Used to populate the quarter filter in the sidebar. Caller can prepend
    "All" or insert a specific year as needed.
    """
    now = datetime.now()
    current_quarter = (now.month - 1) // 3 + 1
    year = now.year

    labels: list[str] = []
    for _ in range(count):
        labels.append(f"{year}Q{current_quarter}")
        current_quarter -= 1
        if current_quarter == 0:
            current_quarter = 4
            year -= 1
    return labels


__all__ = [
    "CATEGORY_COLOURS",
    "STATUS_COLOURS",
    "category_badge",
    "current_and_recent_quarters",
    "format_iso_datetime",
    "score_indicator",
    "status_badge",
]
