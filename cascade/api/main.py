"""FastAPI application entry point.

Exposes liveness and readiness probes from the start so the Docker ``HEALTHCHECK`` and
Kubernetes manifests have something to call. Domain routes are added in subsequent
phases.
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from typing import TYPE_CHECKING

from fastapi import FastAPI
from fastapi.responses import JSONResponse

from cascade._version import __version__
from cascade.config import get_settings

if TYPE_CHECKING:
    from collections.abc import AsyncIterator


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Application lifespan — placeholder for connection pools added in later phases."""
    settings = get_settings()
    app.state.settings = settings
    yield


app = FastAPI(
    title="cascade",
    description="OKR governance platform with multi-agent AI coaching.",
    version=__version__,
    lifespan=lifespan,
    docs_url="/docs",
    redoc_url="/redoc",
    openapi_url="/openapi.json",
)


@app.get("/health", tags=["health"], summary="Liveness probe")
async def health() -> JSONResponse:
    """Return 200 if the process is alive.

    Liveness probes must not depend on external systems — a transient Postgres outage
    should not cause the pod to be killed.
    """
    return JSONResponse({"status": "ok", "version": __version__})


@app.get("/health/ready", tags=["health"], summary="Readiness probe")
async def ready() -> JSONResponse:
    """Return 200 once the service is ready to handle traffic.

    Readiness checks are added in Phase 1 once Postgres and ChromaDB clients are wired
    in. For now this returns 200 unconditionally.
    """
    return JSONResponse({"status": "ready", "version": __version__})
