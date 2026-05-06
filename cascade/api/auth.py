"""API authentication.

This module provides a FastAPI dependency that resolves the calling principal
from a Bearer token. Two modes:

- **Production** — verify the JWT against a configured JWKS endpoint. Real
  provider integration (Auth0, Clerk, AWS Cognito, etc.) is left to the
  deployment. The dependency surface is stable; only the verification body
  changes.
- **Development** — when ``settings.api_auth_mode == "dev"``, any non-empty
  Bearer token is accepted and decoded as a UUID. This lets the UI and curl
  test against a running stack without standing up an identity provider.

The dependency returns a :class:`Principal` carrying ``user_id`` and
``team_id``. Routes use ``Annotated[Principal, Depends(require_principal)]``
so the auth requirement is visible in the route signature and in the
generated OpenAPI document.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Annotated
from uuid import UUID

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from cascade.config import get_settings

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class Principal:
    """The authenticated calling principal."""

    user_id: UUID
    team_id: UUID | None = None


_bearer_scheme = HTTPBearer(auto_error=False, description="JWT Bearer token")


def require_principal(
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer_scheme)],
) -> Principal:
    """Resolve the calling principal from the Authorization header.

    Raises 401 if no token is provided or the token is malformed/invalid.
    """
    if credentials is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing Authorization header",
            headers={"WWW-Authenticate": "Bearer"},
        )

    settings = get_settings()
    token = credentials.credentials

    if settings.api_auth_mode == "dev":
        return _resolve_dev_token(token)
    return _resolve_jwt_token(token)


def _resolve_dev_token(token: str) -> Principal:
    """Dev-mode token resolution.

    The token must be a UUID; that becomes the principal's ``user_id``. This
    intentionally has no signature verification — it's a development
    convenience.
    """
    try:
        user_id = UUID(token)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Dev-mode token must be a UUID; got something else",
            headers={"WWW-Authenticate": "Bearer"},
        ) from exc
    return Principal(user_id=user_id)


def _resolve_jwt_token(token: str) -> Principal:
    """Production JWT verification.

    Stub for the real implementation. A proper implementation pulls JWKS from
    the configured identity provider, verifies the signature and standard
    claims (iss, aud, exp), and extracts the principal from ``sub``.

    Until that's wired in, fail closed — production mode without a verifier
    rejects all tokens. This is intentional: it surfaces the misconfiguration
    immediately rather than silently letting requests through.
    """
    logger.error(
        "Production JWT verification is not yet wired in. "
        "Set CASCADE_API_AUTH_MODE=dev for development, "
        "or configure your identity provider in cascade.api.auth.",
    )
    raise HTTPException(
        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        detail=(
            "JWT verification not configured. Set api_auth_mode=dev for "
            "development or wire in a JWKS verifier."
        ),
    )


__all__ = ["Principal", "require_principal"]
