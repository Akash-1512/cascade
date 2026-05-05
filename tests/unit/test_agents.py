"""Tests for the Drafter and Critic agents using a fake LLM."""

from __future__ import annotations

import json

import pytest

from cascade.agents.contracts import (
    CritiqueResult,
    DimensionScore,
    DraftIteration,
    ProposedKeyResult,
    ProposedObjective,
)
from cascade.agents.critic import PASS_THRESHOLD, CriticError, critique_proposal
from cascade.agents.drafter import DrafterError, draft_objective
from cascade.agents.llm import FakeChatModel
from cascade.domain.enums import MetricType

# --- Sample payloads --------------------------------------------------------

GOOD_PROPOSAL_JSON = json.dumps(
    {
        "title": "Reach product-market fit in the SMB segment",
        "description": "Q2 focus on SMB conversion across two acquisition channels",
        "key_results": [
            {
                "description": "Lift weekly active accounts from 200 to 800",
                "metric_type": "number",
                "baseline_value": 200,
                "target_value": 800,
                "current_value": 200,
                "unit": "accounts",
                "weight": 1.5,
            },
            {
                "description": "Improve trial-to-paid conversion from 12% to 22%",
                "metric_type": "percentage",
                "baseline_value": 12,
                "target_value": 22,
                "current_value": 12,
                "unit": None,
                "weight": 1.0,
            },
            {
                "description": "Reach NPS of 45 across the SMB cohort",
                "metric_type": "number",
                "baseline_value": 32,
                "target_value": 45,
                "current_value": 32,
                "unit": "NPS",
                "weight": 1.0,
            },
        ],
    }
)


PASS_CRITIQUE_JSON = json.dumps(
    {
        "specificity": {
            "score": 0.85,
            "reasoning": "Concrete segment, concrete metrics, clear quarter scope",
        },
        "measurability": {
            "score": 0.9,
            "reasoning": "All KRs have explicit baselines and targets",
        },
        "ambition": {
            "score": 0.75,
            "reasoning": "Targets feel uncomfortable but plausibly achievable",
        },
        "structure": {
            "score": 0.9,
            "reasoning": "Three KRs, qualitative O, mix of metric types is fine",
        },
        "vague_phrases": [],
        "verdict": "pass",
        "suggestions": [],
    }
)


REVISION_CRITIQUE_JSON = json.dumps(
    {
        "specificity": {"score": 0.5, "reasoning": "Too generic — for whom?"},
        "measurability": {"score": 0.85, "reasoning": "ok"},
        "ambition": {"score": 0.7, "reasoning": "borderline"},
        "structure": {"score": 0.9, "reasoning": "ok"},
        "vague_phrases": ["high-quality experience"],
        "verdict": "needs_revision",
        "suggestions": [
            "Replace 'high-quality experience' with the specific cohort and metric",
            "Name the customer segment in the Objective title",
        ],
    }
)


# --- Drafter tests ----------------------------------------------------------


@pytest.mark.unit
async def test_drafter_returns_proposed_objective() -> None:
    model = FakeChatModel(responses=[GOOD_PROPOSAL_JSON])
    proposal = await draft_objective(intent="Reach PMF in SMB", model=model)
    assert isinstance(proposal, ProposedObjective)
    assert proposal.title.startswith("Reach product-market fit")
    assert len(proposal.key_results) == 3


@pytest.mark.unit
async def test_drafter_rejects_empty_intent() -> None:
    model = FakeChatModel(responses=[])
    with pytest.raises(DrafterError, match="must not be empty"):
        await draft_objective(intent="", model=model)


@pytest.mark.unit
async def test_drafter_rejects_whitespace_only_intent() -> None:
    model = FakeChatModel(responses=[])
    with pytest.raises(DrafterError, match="must not be empty"):
        await draft_objective(intent="    ", model=model)


@pytest.mark.unit
async def test_drafter_rejects_invalid_json() -> None:
    model = FakeChatModel(responses=["not valid json {"])
    with pytest.raises(DrafterError):
        await draft_objective(intent="Reach PMF", model=model)


@pytest.mark.unit
async def test_drafter_rejects_proposal_with_no_key_results() -> None:
    payload = json.dumps({"title": "An objective without KRs", "key_results": []})
    model = FakeChatModel(responses=[payload])
    with pytest.raises(DrafterError, match="no Key Results"):
        await draft_objective(intent="x", model=model)


@pytest.mark.unit
async def test_drafter_trims_excess_key_results() -> None:
    payload = json.loads(GOOD_PROPOSAL_JSON)
    extra = payload["key_results"][0]
    # Pad to 7 KRs — Drafter should trim to 5
    payload["key_results"] = [*payload["key_results"], extra, extra, extra, extra]
    model = FakeChatModel(responses=[json.dumps(payload)])
    proposal = await draft_objective(intent="x", model=model)
    assert len(proposal.key_results) == 5


@pytest.mark.unit
async def test_drafter_handles_markdown_fences() -> None:
    fenced = f"```json\n{GOOD_PROPOSAL_JSON}\n```"
    model = FakeChatModel(responses=[fenced])
    proposal = await draft_objective(intent="x", model=model)
    assert len(proposal.key_results) == 3


@pytest.mark.unit
async def test_drafter_uppercase_metric_type_normalised() -> None:
    payload = json.loads(GOOD_PROPOSAL_JSON)
    payload["key_results"][0]["metric_type"] = "NUMBER"
    model = FakeChatModel(responses=[json.dumps(payload)])
    proposal = await draft_objective(intent="x", model=model)
    assert proposal.key_results[0].metric_type == MetricType.NUMBER


# --- Critic tests -----------------------------------------------------------


def _proposal() -> ProposedObjective:
    return ProposedObjective(
        title="Reach product-market fit in the SMB segment",
        key_results=[
            ProposedKeyResult(
                description="Lift weekly active accounts from 200 to 800",
                metric_type=MetricType.NUMBER,
                baseline_value=200,
                target_value=800,
            ),
        ],
    )


@pytest.mark.unit
async def test_critic_returns_critique_result() -> None:
    model = FakeChatModel(responses=[PASS_CRITIQUE_JSON])
    critique = await critique_proposal(proposal=_proposal(), model=model)
    assert isinstance(critique, CritiqueResult)
    assert critique.verdict == "pass"
    assert critique.overall_score >= PASS_THRESHOLD


@pytest.mark.unit
async def test_critic_overrides_pass_when_dimension_below_threshold() -> None:
    """If LLM said pass but a dimension is below threshold, normalise to needs_revision."""
    payload = json.loads(PASS_CRITIQUE_JSON)
    payload["specificity"]["score"] = 0.55  # below threshold
    payload["verdict"] = "pass"  # but the LLM still claims pass
    model = FakeChatModel(responses=[json.dumps(payload)])
    critique = await critique_proposal(proposal=_proposal(), model=model)
    assert critique.verdict == "needs_revision"


@pytest.mark.unit
async def test_critic_preserves_reject_verdict() -> None:
    payload = json.loads(REVISION_CRITIQUE_JSON)
    payload["verdict"] = "reject"
    model = FakeChatModel(responses=[json.dumps(payload)])
    critique = await critique_proposal(proposal=_proposal(), model=model)
    assert critique.verdict == "reject"


@pytest.mark.unit
async def test_critic_rejects_invalid_json() -> None:
    model = FakeChatModel(responses=["{not valid"])
    with pytest.raises(CriticError):
        await critique_proposal(proposal=_proposal(), model=model)


@pytest.mark.unit
async def test_critic_handles_markdown_fences() -> None:
    fenced = f"```\n{PASS_CRITIQUE_JSON}\n```"
    model = FakeChatModel(responses=[fenced])
    critique = await critique_proposal(proposal=_proposal(), model=model)
    assert critique.verdict == "pass"


@pytest.mark.unit
async def test_drafter_uses_iteration_history() -> None:
    """Previous critique suggestions should appear in the rendered prompt."""
    iteration = DraftIteration(
        proposal=_proposal(),
        critique=CritiqueResult(
            specificity=DimensionScore(score=0.5, reasoning="too vague"),
            measurability=DimensionScore(score=0.85, reasoning="ok"),
            ambition=DimensionScore(score=0.7, reasoning="borderline"),
            structure=DimensionScore(score=0.9, reasoning="ok"),
            vague_phrases=["high-quality"],
            verdict="needs_revision",
            suggestions=["Specify the customer segment"],
        ),
        iteration=1,
    )
    model = FakeChatModel(responses=[GOOD_PROPOSAL_JSON])
    await draft_objective(
        intent="Reach PMF in SMB",
        model=model,
        previous_attempts=[iteration],
    )
    # The fake records what was sent — verify the prompt mentions the suggestion
    assert len(model.call_log) == 1
    sent = str(model.call_log[0])
    assert "Specify the customer segment" in sent
    assert "high-quality" in sent
