"""Integration tests for :func:`persist_reflection_themes`."""

from __future__ import annotations

from uuid import uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from cascade.agents.contracts import ReflectionResult, ReflectionTheme
from cascade.agents.reflector_persistence import (
    MIN_OCCURRENCES_TO_PERSIST,
    persist_reflection_themes,
)
from cascade.storage.repositories.organizational_learning import (
    OrganizationalLearningRepository,
)
from tests.integration.factories import seed_team


def _theme(
    *,
    title: str = "Underestimated dependency on data team",
    description: str = "Three OKRs slipped on instrumentation timing in Q2.",
    occurrences: int = 3,
    category: str = "estimation",
) -> ReflectionTheme:
    return ReflectionTheme(
        title=title,
        description=description,
        affected_okr_ids=[str(uuid4()), str(uuid4())],
        occurrences=occurrences,
        category=category,  # type: ignore[arg-type]
    )


def _reflection(themes: list[ReflectionTheme]) -> ReflectionResult:
    return ReflectionResult(
        quarter="2026Q2",
        summary="The quarter held up but had themes worth carrying forward.",
        themes=themes,
        wins=["Shipped analytics rebuild ahead of plan"],
        losses=["Enterprise expansion missed because of integration cost"],
        recommendations=["Move check-ins from Friday to Tuesday"],
    )


@pytest.mark.integration
async def test_persists_themes_above_threshold(session: AsyncSession) -> None:
    team = await seed_team(session)
    repo = OrganizationalLearningRepository(session)

    reflection = _reflection(
        themes=[
            _theme(occurrences=3, title="Recurring data dependency"),
            _theme(occurrences=2, title="Cross-team handoff lag"),
        ]
    )

    persisted = await persist_reflection_themes(
        reflection=reflection,
        team_id=team.id,
        repository=repo,
    )

    assert len(persisted) == 2
    assert {p.title for p in persisted} == {
        "Recurring data dependency",
        "Cross-team handoff lag",
    }


@pytest.mark.integration
async def test_skips_single_occurrence_themes(session: AsyncSession) -> None:
    """occurrences=1 themes are anecdotes, not patterns — don't pollute the trail."""
    team = await seed_team(session)
    repo = OrganizationalLearningRepository(session)

    reflection = _reflection(
        themes=[
            _theme(occurrences=1, title="One-off issue"),
            _theme(occurrences=2, title="Real pattern"),
        ]
    )

    persisted = await persist_reflection_themes(
        reflection=reflection,
        team_id=team.id,
        repository=repo,
    )

    assert len(persisted) == 1
    assert persisted[0].title == "Real pattern"


@pytest.mark.integration
async def test_persisted_themes_are_queryable_by_quarter(
    session: AsyncSession,
) -> None:
    """After persistence, the themes are retrievable through the repository."""
    team = await seed_team(session)
    repo = OrganizationalLearningRepository(session)

    await persist_reflection_themes(
        reflection=_reflection([_theme(title="Q2 theme A")]),
        team_id=team.id,
        repository=repo,
    )
    await session.commit()

    listed = await repo.list_for_team(team.id, quarter="2026Q2")
    assert len(listed) == 1
    assert listed[0].title == "Q2 theme A"
    assert listed[0].quarter == "2026Q2"


@pytest.mark.integration
async def test_no_themes_no_writes(session: AsyncSession) -> None:
    """Empty reflection produces no writes."""
    team = await seed_team(session)
    repo = OrganizationalLearningRepository(session)

    persisted = await persist_reflection_themes(
        reflection=_reflection(themes=[]),
        team_id=team.id,
        repository=repo,
    )
    assert persisted == []


@pytest.mark.integration
async def test_threshold_constant_documents_intent() -> None:
    """The MIN_OCCURRENCES constant is part of the contract — assert visibly."""
    assert MIN_OCCURRENCES_TO_PERSIST == 2
