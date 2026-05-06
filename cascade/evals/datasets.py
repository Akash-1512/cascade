"""Eval dataset loaders.

JSONL files in ``eval_data/`` are the contract — golden drafts, retrieval test
cases, and red-team attacks. Loaders read them strictly: any malformed line
raises immediately so a typo in the dataset is a CI failure rather than a
silently-skipped case.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, ConfigDict, Field

DATA_ROOT = Path(__file__).parent.parent.parent / "eval_data"


# --- Drafting cases ---------------------------------------------------------


class GoldenOKRCase(BaseModel):
    """One labelled OKR drafting case."""

    model_config = ConfigDict(extra="forbid")

    id: str
    role: str
    intent: str
    expected_verdict: str  # 'pass', 'needs_revision', or 'reject'
    expected_min_score: float | None = None
    expected_max_score: float | None = None
    rationale: str


def load_golden_okrs(path: Path | None = None) -> list[GoldenOKRCase]:
    """Load the golden OKR drafts dataset."""
    return _load_jsonl(path or (DATA_ROOT / "golden_okrs.jsonl"), GoldenOKRCase)


# --- Retrieval cases --------------------------------------------------------


class MemoryChunkSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    text: str
    metadata: dict[str, str] = Field(default_factory=dict)


class MemoryQueryCase(BaseModel):
    """One labelled retrieval case.

    The corpus for this case is the ``context_chunks`` list. Retrieval is run
    over those chunks alone — keeping each case self-contained means we don't
    need to pre-seed a database, and the eval is reproducible bit-for-bit.
    """

    model_config = ConfigDict(extra="forbid")

    id: str
    query: str
    context_chunks: list[MemoryChunkSpec]
    expected_relevant_ids: list[str]
    rationale: str


def load_memory_questions(path: Path | None = None) -> list[MemoryQueryCase]:
    """Load the memory retrieval dataset."""
    return _load_jsonl(path or (DATA_ROOT / "memory_questions.jsonl"), MemoryQueryCase)


# --- Red team cases ---------------------------------------------------------


class RedTeamCase(BaseModel):
    """One adversarial test case."""

    model_config = ConfigDict(extra="forbid")

    id: str
    attack_type: str
    intent: str
    expected_behaviour: str
    rationale: str


def load_red_team(path: Path | None = None) -> list[RedTeamCase]:
    """Load the red-team adversarial dataset."""
    return _load_jsonl(path or (DATA_ROOT / "red_team_attacks.jsonl"), RedTeamCase)


# --- Thresholds -------------------------------------------------------------


class Thresholds(BaseModel):
    """Threshold floors loaded from ``eval_data/thresholds.yaml``."""

    model_config = ConfigDict(extra="forbid")

    drafting: dict[str, float]
    critic: dict[str, float]
    retrieval: dict[str, float]
    coaching: dict[str, float] = Field(default_factory=dict)
    red_team: dict[str, float]


def load_thresholds(path: Path | None = None) -> Thresholds:
    """Load the threshold floors."""
    p = path or (DATA_ROOT / "thresholds.yaml")
    payload: dict[str, Any] = yaml.safe_load(p.read_text(encoding="utf-8"))
    return Thresholds.model_validate(payload)


# --- Helpers ----------------------------------------------------------------


def _load_jsonl[T: BaseModel](path: Path, model: type[T]) -> list[T]:
    """Load a JSONL file as a list of validated Pydantic models.

    Strict on parse — a malformed line raises rather than being silently
    skipped.
    """
    if not path.exists():
        raise FileNotFoundError(f"eval dataset missing: {path}")
    cases: list[T] = []
    for lineno, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        try:
            payload = json.loads(stripped)
        except json.JSONDecodeError as exc:
            raise ValueError(f"{path}:{lineno}: invalid JSON: {exc}") from exc
        cases.append(model.model_validate(payload))
    return cases
