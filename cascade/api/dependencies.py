"""FastAPI dependencies."""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Annotated

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from cascade.storage.session import get_sessionmaker


async def get_session() -> AsyncIterator[AsyncSession]:
    """Yield a database session scoped to a single request.

    On exception the session is rolled back; on clean exit it commits.
    Routes accept this via ``Annotated[AsyncSession, Depends(get_session)]``
    so the database boundary is visible in the route signature.
    """
    sessionmaker = get_sessionmaker()
    async with sessionmaker() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise


SessionDep = Annotated[AsyncSession, Depends(get_session)]


__all__ = ["SessionDep", "get_session"]
