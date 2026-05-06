"""Persist Reflector themes as :class:`OrganizationalLearning` rows.

The Reflector itself is pure — it returns a :class:`ReflectionResult` and has
no storage dependencies. This module bridges the agent's output to durable
storage so future Reflectors and human reviewers can pull the team's running
list of recurring patterns.

Themes are persisted with ``occurrences >= 2`` only — single-instance themes
are anecdotes, not patterns, and would dilute the signal.
"""

from __future__ import annotations

from typing import TYPE_CHECKING
from uuid import UUID

from cascade.domain.organizational_learning import OrganizationalLearningCreate

if TYPE_CHECKING:
    from cascade.agents.contracts import ReflectionResult
    from cascade.domain.organizational_learning import OrganizationalLearning
    from cascade.storage.repositories.organizational_learning import (
        OrganizationalLearningRepository,
    )

# Themes with fewer than this many occurrences are not persisted — too anecdotal.
MIN_OCCURRENCES_TO_PERSIST = 2


async def persist_reflection_themes(
    *,
    reflection: ReflectionResult,
    team_id: UUID,
    repository: OrganizationalLearningRepository,
) -> list[OrganizationalLearning]:
    """Persist themes from a reflection result that meet the occurrence threshold.

    Args:
        reflection: The :class:`ReflectionResult` from the Reflector agent.
        team_id: The team whose retrospective this is.
        repository: The :class:`OrganizationalLearningRepository` to write to.

    Returns:
        The list of :class:`OrganizationalLearning` rows that were written.
        Themes below the threshold are silently skipped.
    """
    persisted: list[OrganizationalLearning] = []

    for theme in reflection.themes:
        if theme.occurrences < MIN_OCCURRENCES_TO_PERSIST:
            continue

        learning = await repository.create(
            OrganizationalLearningCreate(
                team_id=team_id,
                quarter=reflection.quarter,
                title=theme.title,
                description=theme.description,
                category=theme.category,
                occurrences=theme.occurrences,
                affected_okr_ids=list(theme.affected_okr_ids),
            )
        )
        persisted.append(learning)

    return persisted


__all__ = ["MIN_OCCURRENCES_TO_PERSIST", "persist_reflection_themes"]
