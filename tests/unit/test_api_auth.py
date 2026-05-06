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
    """Production mode without a real verifier fails closed.

    The intent is to surface the misconfiguration immediately rather than
    silently letting requests through. Wiring an actual JWKS verifier is
    the deployment's responsibility.
    """
    settings = get_settings()
    settings.api_auth_mode = "jwt"
    try:
        creds = HTTPAuthorizationCredentials(scheme="Bearer", credentials="some.jwt.token")
        with pytest.raises(HTTPException) as exc_info:
            require_principal(credentials=creds)
        assert exc_info.value.status_code == 503
        assert "not configured" in exc_info.value.detail
    finally:
        settings.api_auth_mode = "dev"  # reset for other tests


@pytest.mark.unit
def test_principal_is_frozen() -> None:
    p = Principal(user_id=uuid4())
    with pytest.raises(Exception):  # noqa: B017 — frozen dataclass raises FrozenInstanceError
        p.user_id = uuid4()  # type: ignore[misc]
