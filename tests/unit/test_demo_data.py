"""Unit tests for the demo data definitions.

These guard against accidental drift: if someone removes a user but leaves a
decision pointing at them, or removes an OKR but leaves a decision
referencing it, the seed will silently skip rows. The tests catch that
*before* the integration test runs.
"""

from __future__ import annotations

import pytest

from cascade.scripts.demo_data import (
    DECISIONS,
    LEARNINGS,
    OBJECTIVES,
    USERS,
)


@pytest.mark.unit
def test_every_decision_actor_email_matches_a_seeded_user() -> None:
    user_emails = {u.email for u in USERS}
    for decision in DECISIONS:
        assert decision.actor_email in user_emails, (
            f"Decision {decision.summary!r} cites actor {decision.actor_email!r} "
            "but no demo user has that email"
        )


@pytest.mark.unit
def test_every_decision_objective_title_matches_a_seeded_okr() -> None:
    okr_titles = {o.title for o in OBJECTIVES}
    for decision in DECISIONS:
        assert decision.objective_title in okr_titles, (
            f"Decision {decision.summary!r} references unknown OKR title "
            f"{decision.objective_title!r}"
        )


@pytest.mark.unit
def test_every_objective_owner_email_matches_a_seeded_user() -> None:
    user_emails = {u.email for u in USERS}
    for okr in OBJECTIVES:
        assert okr.owner_email in user_emails, (
            f"Objective {okr.title!r} has owner {okr.owner_email!r} but no demo user has that email"
        )


@pytest.mark.unit
def test_every_kr_weight_sums_to_one_per_objective() -> None:
    """A non-summing weight set is technically allowed but probably a bug —
    the demo content should model what reviewers expect to see."""
    for okr in OBJECTIVES:
        total_weight = sum(kr.weight for kr in okr.key_results)
        assert abs(total_weight - 1.0) < 0.001, (
            f"OKR {okr.title!r} has KR weights summing to {total_weight}, not 1.0"
        )


@pytest.mark.unit
def test_quarters_are_in_supported_range() -> None:
    for okr in OBJECTIVES:
        assert 1 <= okr.quarter_q <= 4, f"OKR {okr.title!r} has invalid quarter {okr.quarter_q}"
        assert 2020 <= okr.quarter_year <= 2030, (
            f"OKR {okr.title!r} has implausible year {okr.quarter_year}"
        )


@pytest.mark.unit
def test_learnings_quarter_format() -> None:
    """Quarters use the 'YYYYQ[1-4]' format the API expects."""
    import re

    pattern = re.compile(r"^\d{4}Q[1-4]$")
    for learning in LEARNINGS:
        assert pattern.match(learning.quarter), (
            f"Learning {learning.title!r} has bad quarter format: {learning.quarter!r}"
        )


@pytest.mark.unit
def test_decisions_have_at_least_one_alternative_or_evidence() -> None:
    """A decision with neither alternatives nor evidence is just a note —
    the demo should show off the cascade pattern, not the degenerate one."""
    weak_decisions: list[str] = []
    for decision in DECISIONS:
        if not decision.alternatives and not decision.evidence:
            weak_decisions.append(decision.summary)
    # We allow some — like an OBJECTIVE_CLOSE — but not most.
    assert len(weak_decisions) <= 1, (
        f"{len(weak_decisions)} decisions have no alternatives and no evidence; "
        "the demo should show the alternatives-considered pattern. "
        f"Weak decisions: {weak_decisions}"
    )


@pytest.mark.unit
def test_demo_content_counts_are_stable() -> None:
    """If these counts change, the docs and CHANGELOG need updating too."""
    assert len(USERS) == 2
    assert len(OBJECTIVES) == 3
    assert len(DECISIONS) == 8
    assert len(LEARNINGS) == 3
