"""FastAPI application entry point.

Run locally with::

    uvicorn cascade.api.main:app --reload --host 0.0.0.0 --port 8000

OpenAPI docs at ``/docs``; the schema lives at ``/openapi.json``.
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from typing import TYPE_CHECKING

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import text

from cascade._version import __version__
from cascade.api.routes import checkins, decisions, learnings, okrs
from cascade.api.schemas import HealthResponse
from cascade.config import get_settings
from cascade.storage.session import get_sessionmaker

if TYPE_CHECKING:
    from collections.abc import AsyncIterator


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Application lifespan — initialise shared resources, tear them down on exit."""
    settings = get_settings()
    app.state.settings = settings
    app.state.sessionmaker = get_sessionmaker()
    yield


app = FastAPI(
    title="cascade",
    description=(
        "OKR governance platform with multi-agent AI coaching. Read endpoints "
        "for OKRs, decisions, and organizational learnings; mutation endpoints "
        "for committing aligned drafts, logging decisions and check-ins, and "
        "recording learnings. Mid-life agent-driven mutations (target changes, "
        "draft pause-and-resume) flow through the MCP server where the agent "
        "loop lives."
    ),
    version=__version__,
    lifespan=lifespan,
    docs_url="/docs",
    redoc_url="/redoc",
    openapi_url="/openapi.json",
)

_settings = get_settings()
app.add_middleware(
    CORSMiddleware,
    allow_origins=_settings.api_cors_allow_origins,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type"],
)

app.include_router(okrs.router)
app.include_router(decisions.router)
app.include_router(learnings.router)
app.include_router(checkins.router)


@app.get(
    "/health",
    response_model=HealthResponse,
    tags=["health"],
    summary="Liveness probe",
)
async def health() -> HealthResponse:
    """Return 200 if the process is alive.

    Liveness probes must not depend on external systems — a transient
    Postgres outage should not cause the pod to be killed.
    """
    settings = get_settings()
    return HealthResponse(status="ok", version=__version__, cascade_env=settings.cascade_env)


@app.get(
    "/health/ready",
    response_model=HealthResponse,
    tags=["health"],
    summary="Readiness probe",
)
async def ready() -> HealthResponse:
    """Return 200 once the service is ready to handle traffic.

    Verifies the database is reachable. ChromaDB readiness is checked lazily
    on first use — failing readiness on ChromaDB unavailability would block
    every request, even those that don't touch the vector store.
    """
    settings = get_settings()
    sessionmaker = getattr(app.state, "sessionmaker", None) or get_sessionmaker()
    async with sessionmaker() as session:
        await session.execute(text("SELECT 1"))
    return HealthResponse(status="ready", version=__version__, cascade_env=settings.cascade_env)


__all__ = ["app"]
