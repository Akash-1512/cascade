# syntax=docker/dockerfile:1.7

# ---- Builder stage --------------------------------------------------------
# Builds a wheel for cascade. Kept separate from runtime so the final image
# doesn't carry build-essential or libpq-dev.
FROM python:3.12-slim AS builder

ENV PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /build

RUN apt-get update \
    && apt-get install -y --no-install-recommends build-essential libpq-dev \
    && rm -rf /var/lib/apt/lists/*

COPY pyproject.toml README.md LICENSE ./
COPY cascade ./cascade

# Build the cascade wheel, then collect every wheel needed for the
# [ui,observability] extras. The runtime stage installs from this wheel
# cache offline — keeps the final image hermetic and reproducible.
RUN pip install --upgrade pip build \
    && python -m build --wheel \
    && pip wheel --wheel-dir /wheels "./dist/cascade-"*.whl \
    && pip wheel --wheel-dir /wheels "./dist/cascade-"*.whl"[ui,observability]"

# ---- Runtime stage --------------------------------------------------------
# Minimal image: libpq5 for psycopg, curl for ad-hoc probing, non-root user,
# nothing else. ~150MB compressed.
FROM python:3.12-slim AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

RUN apt-get update \
    && apt-get install -y --no-install-recommends libpq5 curl \
    && rm -rf /var/lib/apt/lists/* \
    && groupadd --system cascade \
    && useradd --system --gid cascade --home /app --shell /usr/sbin/nologin cascade

WORKDIR /app

# Offline install from the builder's wheel cache. --no-deps because the
# wheel cache already contains every transitive dep — refusing to consult
# PyPI here is the hermeticity guarantee.
COPY --from=builder /wheels /wheels
RUN pip install --no-index --find-links=/wheels "cascade[ui,observability]" \
    && rm -rf /wheels

USER cascade

# Informational. The actual ports each container binds are set by the
# command line at run time (uvicorn --port, streamlit --server.port, MCP
# server --port). Listed for documentation:
#   8000 — REST API (uvicorn cascade.api.main:app)
#   8501 — Streamlit operator console
#   8765 — MCP server (sse transport)
EXPOSE 8000 8501 8765

# No image-level HEALTHCHECK. The image runs three different services
# (API, MCP, UI) and each has its own liveness/readiness shape. The Helm
# chart's per-deployment probes are the authoritative health signal;
# adding a HEALTHCHECK here would either be wrong for two of the three
# services or duplicate what Kubernetes already does.

# Default command runs the REST API. The Helm chart overrides this in the
# MCP and UI deployments — same image, different `command:` per pod.
CMD ["uvicorn", "cascade.api.main:app", "--host", "0.0.0.0", "--port", "8000"]
