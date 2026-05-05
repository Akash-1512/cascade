"""Repository pattern — the boundary between persistence and domain.

Repositories take and return :mod:`cascade.domain` value objects, never ORM rows.
This isolates the rest of the codebase from SQLAlchemy concerns, makes services
testable with in-memory fakes, and makes it possible to swap storage backends without
touching agent or API code.

Each repository owns one aggregate root (Team, User, Objective, Decision). Aggregates
that depend on each other (e.g., a check-in cannot exist without its key result) are
loaded together by their root's repository.
"""

from __future__ import annotations

from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession


class RepositoryError(Exception):
    """Base class for all repository errors."""


class NotFoundError(RepositoryError):
    """Requested entity was not found."""

    def __init__(self, entity: str, identifier: UUID | str) -> None:
        super().__init__(f"{entity} not found: {identifier}")
        self.entity = entity
        self.identifier = identifier


class DuplicateError(RepositoryError):
    """An attempt to create an entity that violates a uniqueness constraint."""

    def __init__(self, entity: str, field: str, value: str) -> None:
        super().__init__(f"{entity} with {field}={value!r} already exists")
        self.entity = entity
        self.field = field
        self.value = value


class BaseRepository[T]:
    """Common helpers for repositories. Subclasses define the type-specific methods."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    @property
    def session(self) -> AsyncSession:
        """Expose the bound session for advanced queries."""
        return self._session
