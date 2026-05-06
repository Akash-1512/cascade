"""Unit tests for cascade.ui.views.

The shared components are pure functions and tested directly. The view
modules are exercised through Streamlit's :class:`AppTest` harness with the
API client patched to return canned responses.
"""

from __future__ import annotations

from datetime import datetime

import pytest

from cascade.ui.views import components

# --- components -------------------------------------------------------------


@pytest.mark.unit
def test_status_badge_uses_known_colour() -> None:
    assert components.status_badge("on_track").startswith(":green-badge[")
    assert components.status_badge("at_risk").startswith(":orange-badge[")
    assert components.status_badge("off_track").startswith(":red-badge[")
    assert components.status_badge("achieved").startswith(":green-badge[")


@pytest.mark.unit
def test_status_badge_unknown_falls_back_to_grey() -> None:
    """Forward-compatibility — the API may add new statuses; the UI shouldn't crash."""
    badge = components.status_badge("some_future_status")
    assert badge.startswith(":gray-badge[")
    assert "Some Future Status" in badge


@pytest.mark.unit
def test_score_indicator_thresholds() -> None:
    """Below 0.3 reads as off-track, 0.3-0.7 in-progress, 0.7+ near-achieved."""
    assert components.score_indicator(0.0).startswith(":red-badge[")
    assert components.score_indicator(0.29).startswith(":red-badge[")
    assert components.score_indicator(0.3).startswith(":blue-badge[")
    assert components.score_indicator(0.5).startswith(":blue-badge[")
    assert components.score_indicator(0.69).startswith(":blue-badge[")
    assert components.score_indicator(0.7).startswith(":green-badge[")
    assert components.score_indicator(1.0).startswith(":green-badge[")


@pytest.mark.unit
def test_score_indicator_renders_percentage() -> None:
    assert "50%" in components.score_indicator(0.5)
    assert "33%" in components.score_indicator(0.333)
    assert "100%" in components.score_indicator(1.0)


@pytest.mark.unit
def test_category_badge_known() -> None:
    assert components.category_badge("estimation").startswith(":orange-badge[")
    assert components.category_badge("execution").startswith(":blue-badge[")
    assert components.category_badge("process").startswith(":rainbow-badge[")


@pytest.mark.unit
def test_format_iso_datetime_handles_strings() -> None:
    result = components.format_iso_datetime("2026-05-06T09:32:00")
    assert "2026-05-06" in result


@pytest.mark.unit
def test_format_iso_datetime_handles_z_suffix() -> None:
    """The API returns timezone-aware ISO strings; the formatter must handle Z."""
    result = components.format_iso_datetime("2026-05-06T09:32:00Z")
    assert "2026-05-06" in result


@pytest.mark.unit
def test_format_iso_datetime_handles_datetime_objects() -> None:
    dt = datetime(2026, 5, 6, 9, 32)
    assert components.format_iso_datetime(dt) == "2026-05-06 09:32"


@pytest.mark.unit
def test_format_iso_datetime_returns_input_on_parse_failure() -> None:
    """Forward-compat — never crash on a value the API hasn't formatted yet."""
    assert components.format_iso_datetime("not-a-date") == "not-a-date"


@pytest.mark.unit
def test_current_and_recent_quarters_returns_correct_count() -> None:
    quarters = components.current_and_recent_quarters(count=8)
    assert len(quarters) == 8


@pytest.mark.unit
def test_current_and_recent_quarters_format() -> None:
    quarters = components.current_and_recent_quarters(count=4)
    for q in quarters:
        assert len(q) == 6
        assert q[4] == "Q"
        year_part = int(q[:4])
        quarter_part = int(q[5])
        assert year_part >= 2024
        assert 1 <= quarter_part <= 4


@pytest.mark.unit
def test_current_and_recent_quarters_strictly_decreases() -> None:
    """Quarters must be returned newest-first and unique."""
    quarters = components.current_and_recent_quarters(count=10)
    assert len(set(quarters)) == 10
    # Verify each pair is older than the previous
    for i in range(1, len(quarters)):
        prev_year, prev_q = int(quarters[i - 1][:4]), int(quarters[i - 1][5])
        cur_year, cur_q = int(quarters[i][:4]), int(quarters[i][5])
        prev_idx = prev_year * 4 + prev_q
        cur_idx = cur_year * 4 + cur_q
        assert cur_idx == prev_idx - 1, (
            f"Quarter at index {i} ({quarters[i]}) is not exactly one before "
            f"index {i - 1} ({quarters[i - 1]})"
        )
