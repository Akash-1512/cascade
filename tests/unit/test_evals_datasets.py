"""Tests for :mod:`cascade.evals.datasets`."""

from __future__ import annotations

from pathlib import Path

import pytest

from cascade.evals.datasets import (
    GoldenOKRCase,
    MemoryQueryCase,
    RedTeamCase,
    Thresholds,
    _load_jsonl,
    load_golden_okrs,
    load_memory_questions,
    load_red_team,
    load_thresholds,
)


@pytest.mark.unit
def test_load_golden_okrs_returns_30_cases() -> None:
    cases = load_golden_okrs()
    assert len(cases) == 30
    assert all(isinstance(c, GoldenOKRCase) for c in cases)


@pytest.mark.unit
def test_golden_dataset_balanced_across_verdicts() -> None:
    """Verifies the dataset has 10 of each verdict — sanity check on contents."""
    cases = load_golden_okrs()
    verdicts = [c.expected_verdict for c in cases]
    assert verdicts.count("pass") == 10
    assert verdicts.count("needs_revision") == 10
    assert verdicts.count("reject") == 10


@pytest.mark.unit
def test_golden_dataset_covers_multiple_roles() -> None:
    cases = load_golden_okrs()
    roles = {c.role for c in cases}
    assert len(roles) >= 8  # diverse role coverage


@pytest.mark.unit
def test_load_memory_questions_returns_10_cases() -> None:
    cases = load_memory_questions()
    assert len(cases) == 10
    assert all(isinstance(c, MemoryQueryCase) for c in cases)


@pytest.mark.unit
def test_memory_questions_have_self_contained_corpora() -> None:
    """Every expected_relevant_id must appear in that case's context_chunks."""
    cases = load_memory_questions()
    for case in cases:
        chunk_ids = {c.id for c in case.context_chunks}
        for expected_id in case.expected_relevant_ids:
            assert expected_id in chunk_ids, (
                f"case {case.id}: expected id {expected_id!r} not in context_chunks"
            )


@pytest.mark.unit
def test_load_red_team_returns_six_cases() -> None:
    cases = load_red_team()
    assert len(cases) == 6
    assert all(isinstance(c, RedTeamCase) for c in cases)


@pytest.mark.unit
def test_red_team_covers_six_attack_types() -> None:
    cases = load_red_team()
    attack_types = {c.attack_type for c in cases}
    assert attack_types == {
        "vague_okr_injection",
        "sandbagging",
        "target_gaming",
        "prompt_injection_via_intent",
        "decision_laundering",
        "memory_poisoning",
    }


@pytest.mark.unit
def test_load_thresholds_returns_structured_floors() -> None:
    t = load_thresholds()
    assert isinstance(t, Thresholds)
    assert t.drafting["f1_min"] == 0.85
    assert t.red_team["pass_rate_min"] == 0.95


@pytest.mark.unit
def test_load_jsonl_strict_on_malformed(tmp_path: Path) -> None:
    """Malformed lines raise immediately — no silent skipping."""
    path = tmp_path / "broken.jsonl"
    path.write_text(
        '{"id": "1", "role": "x", "intent": "y", "expected_verdict": "pass", "rationale": "z"}\n'
        "this is not json\n",
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="invalid JSON"):
        _load_jsonl(path, GoldenOKRCase)


@pytest.mark.unit
def test_load_jsonl_skips_blank_and_comment_lines(tmp_path: Path) -> None:
    path = tmp_path / "ok.jsonl"
    path.write_text(
        "# this is a comment\n"
        "\n"
        '{"id": "1", "role": "x", "intent": "y", "expected_verdict": "pass", "rationale": "z"}\n',
        encoding="utf-8",
    )
    result = _load_jsonl(path, GoldenOKRCase)
    assert len(result) == 1


@pytest.mark.unit
def test_load_jsonl_raises_on_missing_file(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError, match="missing"):
        _load_jsonl(tmp_path / "does-not-exist.jsonl", GoldenOKRCase)
