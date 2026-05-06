"""Domain models for organizational learning.

Themes distilled from quarterly retrospectives. Persisted to Postgres so
future Reflectors can see prior learnings, and so a quarterly review can pull
the org's running list of recurring issues.

Themes are immutable. To express that a theme has been addressed, write a new
``OrganizationalLearningCreate`` with ``supersedes_id`` set rather than
updating the original.
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

LearningCategory = Literal[
    "execution", "planning", "alignment", "estimation", "external", "process"
]


class OrganizationalLearning(BaseModel):
    """A learning theme as stored in Postgres."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    id: UUID
    team_id: UUID
    quarter: str = Field(pattern=r"^\d{4}Q[1-4]$")
    title: str = Field(min_length=1, max_length=200)
    description: str = Field(min_length=1, max_length=2000)
    category: LearningCategory
    occurrences: int = Field(ge=1)
    affected_okr_ids: list[str] = Field(default_factory=list)
    supersedes_id: UUID | None = None
    created_at: datetime


class OrganizationalLearningCreate(BaseModel):
    """Payload for creating a new learning theme."""

    model_config = ConfigDict(extra="forbid")

    team_id: UUID
    quarter: str = Field(pattern=r"^\d{4}Q[1-4]$")
    title: str = Field(min_length=1, max_length=200)
    description: str = Field(min_length=1, max_length=2000)
    category: LearningCategory
    occurrences: int = Field(ge=1)
    affected_okr_ids: list[str] = Field(default_factory=list)
    supersedes_id: UUID | None = None
