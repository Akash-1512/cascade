"""Tests for prompt template rendering."""

from __future__ import annotations

import pytest
from jinja2 import UndefinedError

from cascade.agents.contracts import (
    CritiqueResult,
    DimensionScore,
    DraftIteration,
    ProposedKeyResult,
    ProposedObjective,
)
from cascade.agents.prompts import list_prompts, render_prompt
from cascade.domain.enums import MetricType


@pytest.mark.unit
def test_lists_known_prompts() -> None:
    prompts = list_prompts()
    assert "drafter" in prompts
    assert "critic" in prompts


@pytest.mark.unit
def test_drafter_prompt_renders_with_minimum_context() -> None:
    rendered = render_prompt(
        "drafter",
        intent="Reach PMF in SMB",
        parent_objective=None,
        previous_attempts=[],
    )
    assert "Reach PMF in SMB" in rendered
    assert "Drafter" in rendered  # role anchor — model knows it is the Drafter
    assert "Iteration history" not in rendered  # no iterations yet


@pytest.mark.unit
def test_drafter_prompt_includes_iteration_history() -> None:
    iteration = DraftIteration(
        proposal=ProposedObjective(
            title="A draft title that meets the minimum length",
            key_results=[
                ProposedKeyResult(
                    description="Lift weekly active accounts from 200 to 800",
                    metric_type=MetricType.NUMBER,
                    baseline_value=200,
                    target_value=800,
                )
            ],
        ),
        critique=CritiqueResult(
            specificity=DimensionScore(score=0.5, reasoning="too vague"),
            measurability=DimensionScore(score=0.8, reasoning="ok"),
            ambition=DimensionScore(score=0.7, reasoning="borderline"),
            structure=DimensionScore(score=0.9, reasoning="good"),
            vague_phrases=["high-quality"],
            verdict="needs_revision",
            suggestions=["Specify the customer segment", "Replace 'high-quality'"],
        ),
        iteration=1,
    )
    rendered = render_prompt(
        "drafter",
        intent="Reach PMF in SMB",
        parent_objective=None,
        previous_attempts=[iteration],
    )
    assert "Iteration history" in rendered
    assert "Specify the customer segment" in rendered
    assert "high-quality" in rendered


@pytest.mark.unit
def test_critic_prompt_includes_proposal_details() -> None:
    proposal = ProposedObjective(
        title="Reach NPS of 45 across the SMB cohort this quarter",
        description="Q2 focus is SMB conversion",
        key_results=[
            ProposedKeyResult(
                description="Lift weekly active accounts from 200 to 800",
                metric_type=MetricType.NUMBER,
                baseline_value=200,
                target_value=800,
                unit="accounts",
            ),
            ProposedKeyResult(
                description="Improve trial-to-paid conversion from 12% to 22%",
                metric_type=MetricType.PERCENTAGE,
                baseline_value=12,
                target_value=22,
            ),
        ],
    )
    rendered = render_prompt("critic", proposal=proposal)
    assert "Reach NPS of 45" in rendered
    assert "Lift weekly active accounts from 200 to 800" in rendered
    assert "200 → 800" in rendered
    assert "Q2 focus is SMB conversion" in rendered


@pytest.mark.unit
def test_undefined_variable_raises() -> None:
    """StrictUndefined ensures missing variables fail loudly."""
    with pytest.raises(UndefinedError):
        render_prompt("drafter", intent="x")  # missing parent_objective and previous_attempts


@pytest.mark.unit
def test_unknown_template_raises() -> None:
    from jinja2 import TemplateNotFound

    with pytest.raises(TemplateNotFound):
        render_prompt("not-a-real-template", x=1)
