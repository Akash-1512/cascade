"""Tests for :mod:`cascade.api.auth`."""

from __future__ import annotations

from uuid import uuid4

import pytest
from fastapi import HTTPException
from fastapi.security import HTTPAuthorizationCredentials

from cascade.api.auth import Principal, require_principal
from cascade.config import get_settings


@pytest.mark.unit
def test_missing_credentials_raises_401() -> None:
    with pytest.raises(HTTPException) as exc_info:
        require_principal(credentials=None)
    assert exc_info.value.status_code == 401
    assert "Missing" in exc_info.value.detail


@pytest.mark.unit
def test_dev_mode_accepts_uuid_token() -> None:
    """In dev mode, a UUID token resolves to a Principal."""
    settings = get_settings()
    settings.api_auth_mode = "dev"

    user_id = uuid4()
    creds = HTTPAuthorizationCredentials(scheme="Bearer", credentials=str(user_id))
    principal = require_principal(credentials=creds)

    assert isinstance(principal, Principal)
    assert principal.user_id == user_id
    assert principal.team_id is None


@pytest.mark.unit
def test_dev_mode_rejects_non_uuid() -> None:
    settings = get_settings()
    settings.api_auth_mode = "dev"

    creds = HTTPAuthorizationCredentials(scheme="Bearer", credentials="not-a-uuid")
    with pytest.raises(HTTPException) as exc_info:
        require_principal(credentials=creds)
    assert exc_info.value.status_code == 401
    assert "UUID" in exc_info.value.detail


@pytest.mark.unit
def test_jwt_mode_returns_503_when_unconfigured() -> None:
    """Production mode without configured JWKS/issuer/audience fails closed.

    The intent is to surface the misconfiguration immediately rather than
    silently letting requests through. Wiring an actual JWKS verifier is
    the deployment's responsibility — this test only asserts that the
    failure is loud and surfaced as a 503 with an actionable message.
    """
    from cascade.api import jwt_verifier as jwt_verifier_module

    settings = get_settings()
    saved_mode = settings.api_auth_mode
    saved_url = settings.api_jwks_url
    saved_issuer = settings.api_jwt_issuer
    saved_audience = settings.api_jwt_audience

    settings.api_auth_mode = "jwt"
    settings.api_jwks_url = None
    settings.api_jwt_issuer = None
    settings.api_jwt_audience = None
    jwt_verifier_module.reset_verifier()
    try:
        creds = HTTPAuthorizationCredentials(scheme="Bearer", credentials="some.jwt.token")
        with pytest.raises(HTTPException) as exc_info:
            require_principal(credentials=creds)
        assert exc_info.value.status_code == 503
        # Detail names the missing settings so an operator can fix it.
        assert "api_jwks_url" in exc_info.value.detail
    finally:
        settings.api_auth_mode = saved_mode
        settings.api_jwks_url = saved_url
        settings.api_jwt_issuer = saved_issuer
        settings.api_jwt_audience = saved_audience
        jwt_verifier_module.reset_verifier()


@pytest.mark.unit
def test_principal_is_frozen() -> None:
    p = Principal(user_id=uuid4())
    with pytest.raises(Exception):  # noqa: B017 — frozen dataclass raises FrozenInstanceError
        p.user_id = uuid4()  # type: ignore[misc]
