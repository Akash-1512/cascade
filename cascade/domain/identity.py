"""User and Team domain models.

These are the identity primitives the rest of the domain references. Authentication
and authorisation logic lives in ``cascade.api.auth`` — these models carry only the
identity, role, and team attributes.
"""

from __future__ import annotations

from datetime import datetime
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, EmailStr, Field

from cascade.domain.enums import UserRole


class Team(BaseModel):
    """A unit that owns OKRs.

    Teams form a tree via ``parent_team_id``. The root of the tree is the company.
    There is no constraint that the tree be balanced or shallow — a six-level
    org chart is valid.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    id: UUID = Field(default_factory=uuid4)
    name: str = Field(min_length=1, max_length=100)
    slug: str = Field(
        pattern=r"^[a-z0-9][a-z0-9-]*[a-z0-9]$|^[a-z0-9]$",
        min_length=1,
        max_length=50,
        description="URL-safe identifier; lowercase, hyphen-separated.",
    )
    parent_team_id: UUID | None = None
    created_at: datetime
    updated_at: datetime


class User(BaseModel):
    """A person interacting with cascade.

    Users have exactly one home team but may have visibility into other teams via
    role-based scopes (configured at the API layer).
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    id: UUID = Field(default_factory=uuid4)
    email: EmailStr
    full_name: str = Field(min_length=1, max_length=200)
    role: UserRole
    team_id: UUID
    is_active: bool = True
    created_at: datetime
    updated_at: datetime


class UserCreate(BaseModel):
    """Payload for creating a user via the API.

    Distinct from :class:`User` because the database assigns ``id`` and timestamps,
    and because ``password`` is accepted on create but never returned.
    """

    model_config = ConfigDict(extra="forbid")

    email: EmailStr
    full_name: str = Field(min_length=1, max_length=200)
    role: UserRole = UserRole.CONTRIBUTOR
    team_id: UUID
    password: str = Field(min_length=12, max_length=200)


class TeamCreate(BaseModel):
    """Payload for creating a team via the API."""

    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=100)
    slug: str = Field(
        pattern=r"^[a-z0-9][a-z0-9-]*[a-z0-9]$|^[a-z0-9]$",
        min_length=1,
        max_length=50,
    )
    parent_team_id: UUID | None = None
