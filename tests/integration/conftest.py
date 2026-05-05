"""Shared integration-test fixtures.

By default integration tests run against an in-memory SQLite database for fast
feedback. Setting the ``CASCADE_TEST_DATABASE_URL`` environment variable points the
suite at a real Postgres instance — CI uses this to run the same tests against the
production database engine.

SQLite does not support Postgres-native types (ENUM, JSONB), so the SQLAlchemy types
are downgraded to portable equivalents (String, JSON) when the test URL begins with
``sqlite``. The application code never sees this — only the test fixtures do.
"""

from __future__ import annotations

import os
from collections.abc import AsyncIterator
from typing import Any
from uuid import UUID

import pytest
import pytest_asyncio
from sqlalchemy import JSON, String
from sqlalchemy.dialects.postgresql import ENUM as PG_ENUM, JSONB, UUID as PG_UUID
from sqlalchemy.engine.interfaces import Dialect
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.types import CHAR, TypeDecorator

from cascade.storage import (
    Base,
    models as orm_models,  # noqa: F401 — register tables
)


class _UUIDString(TypeDecorator[UUID]):
    """SQLite-compatible UUID storage as 36-char string with ↔ UUID conversion."""

    impl = CHAR(36)
    cache_ok = True

    def process_bind_param(self, value: Any | None, dialect: Dialect) -> str | None:
        if value is None:
            return None
        if isinstance(value, UUID):
            return str(value)
        return str(UUID(str(value)))

    def process_result_value(self, value: Any | None, dialect: Dialect) -> UUID | None:
        if value is None:
            return None
        if isinstance(value, UUID):
            return value
        return UUID(str(value))


def _patch_postgres_types_for_sqlite() -> None:
    """Substitute Postgres-only column types with portable equivalents.

    Idempotent — calling twice is safe. We mutate the existing Table objects in place
    because the test runtime imports them transitively before this fixture runs.
    """
    for table in Base.metadata.tables.values():
        for column in table.columns:
            ctype = column.type
            if isinstance(ctype, PG_ENUM):
                # Preserve the value-set as a CHECK could be added — for simplicity
                # we coerce to String. SQLAlchemy's PG_ENUM enforces values at
                # assignment time anyway via the python enum subclass.
                column.type = String(64)
            elif isinstance(ctype, JSONB):
                column.type = JSON()
            elif isinstance(ctype, PG_UUID):
                column.type = _UUIDString()


def _resolve_test_url() -> str:
    return os.environ.get(
        "CASCADE_TEST_DATABASE_URL",
        "sqlite+aiosqlite:///:memory:",
    )


@pytest_asyncio.fixture
async def engine() -> AsyncIterator[AsyncEngine]:
    """An async engine bound to the test database, schema fresh per test."""
    url = _resolve_test_url()
    if url.startswith("sqlite"):
        _patch_postgres_types_for_sqlite()

    engine = create_async_engine(url, echo=False)

    if url.startswith("sqlite"):
        # SQLite has FK constraints disabled by default. Turn them on per
        # connection so test semantics match Postgres.
        from sqlalchemy import event
        from sqlalchemy.engine import Engine

        @event.listens_for(Engine, "connect")
        def _enable_sqlite_fk(dbapi_connection: Any, _: Any) -> None:
            cursor = dbapi_connection.cursor()
            cursor.execute("PRAGMA foreign_keys=ON")
            cursor.close()

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    try:
        yield engine
    finally:
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.drop_all)
        await engine.dispose()


@pytest_asyncio.fixture
async def session(engine: AsyncEngine) -> AsyncIterator[AsyncSession]:
    """An async session bound to the test engine."""
    sessionmaker = async_sessionmaker(bind=engine, expire_on_commit=False, autoflush=False)
    async with sessionmaker() as s:
        yield s


@pytest.fixture
def is_postgres() -> bool:
    """Tests can branch on this when behaviour legitimately differs by backend."""
    return _resolve_test_url().startswith("postgresql")
