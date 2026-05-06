"""End-to-end tests for :func:`require_principal` in JWT mode.

The unit tests in ``test_api_auth.py`` cover dev mode and JWT mode's
unconfigured (503) path. These cover JWT mode wired up to a real verifier
backed by an httpx-mocked JWKS endpoint.

We patch the module-level singleton in :mod:`cascade.api.jwt_verifier` so
the auth dependency picks up the test-configured verifier rather than
trying to read the production settings.
"""

from __future__ import annotations

from uuid import uuid4

import pytest
from fastapi import HTTPException
from fastapi.security import HTTPAuthorizationCredentials

from cascade.api import jwt_verifier as jwt_verifier_module
from cascade.api.auth import Principal, require_principal
from cascade.api.jwt_verifier import JWKSClient, JWTVerifier
from cascade.config import get_settings
from tests.unit._jwt_helpers import (
    jwks_failing_transport,
    jwks_transport,
    make_keypair,
)

JWKS_URL = "https://test-issuer.example.com/jwks.json"
ISSUER = "https://test-issuer.example.com/"
AUDIENCE = "cascade-api"


@pytest.fixture
def jwt_mode():
    """Switch the auth dependency into JWT mode for one test, then reset."""
    settings = get_settings()
    original_mode = settings.api_auth_mode
    settings.api_auth_mode = "jwt"
    yield
    settings.api_auth_mode = original_mode
    jwt_verifier_module.reset_verifier()


def _install_test_verifier(keypair) -> None:
    """Install a test-configured singleton so get_verifier returns it."""
    client = JWKSClient(transport=jwks_transport(keypair, jwks_url=JWKS_URL))
    verifier = JWTVerifier(
        jwks_client=client,
        jwks_url=JWKS_URL,
        issuer=ISSUER,
        audience=AUDIENCE,
    )
    jwt_verifier_module._verifier = verifier


@pytest.mark.unit
def test_jwt_mode_with_valid_token_returns_principal(jwt_mode) -> None:
    keypair = make_keypair()
    _install_test_verifier(keypair)

    user_id = uuid4()
    token = keypair.mint(sub=user_id, issuer=ISSUER, audience=AUDIENCE)
    creds = HTTPAuthorizationCredentials(scheme="Bearer", credentials=token)

    principal = require_principal(credentials=creds)
    assert isinstance(principal, Principal)
    assert principal.user_id == user_id


@pytest.mark.unit
def test_jwt_mode_expired_token_returns_401(jwt_mode) -> None:
    keypair = make_keypair()
    _install_test_verifier(keypair)

    token = keypair.mint(issuer=ISSUER, audience=AUDIENCE, expires_in_seconds=-3600)
    creds = HTTPAuthorizationCredentials(scheme="Bearer", credentials=token)

    with pytest.raises(HTTPException) as exc_info:
        require_principal(credentials=creds)
    assert exc_info.value.status_code == 401
    # Detail is intentionally generic — a verifier shouldn't help an
    # attacker distinguish "wrong issuer" from "expired" from "bad sig".
    assert "invalid or expired" in exc_info.value.detail.lower()


@pytest.mark.unit
def test_jwt_mode_wrong_issuer_returns_401(jwt_mode) -> None:
    keypair = make_keypair()
    _install_test_verifier(keypair)

    token = keypair.mint(issuer="https://attacker/", audience=AUDIENCE)
    creds = HTTPAuthorizationCredentials(scheme="Bearer", credentials=token)

    with pytest.raises(HTTPException) as exc_info:
        require_principal(credentials=creds)
    assert exc_info.value.status_code == 401


@pytest.mark.unit
def test_jwt_mode_jwks_unreachable_returns_503(jwt_mode) -> None:
    """Provider outage is a service problem, not a credential problem."""
    keypair = make_keypair()
    client = JWKSClient(transport=jwks_failing_transport())
    verifier = JWTVerifier(
        jwks_client=client,
        jwks_url=JWKS_URL,
        issuer=ISSUER,
        audience=AUDIENCE,
    )
    jwt_verifier_module._verifier = verifier

    token = keypair.mint(issuer=ISSUER, audience=AUDIENCE)
    creds = HTTPAuthorizationCredentials(scheme="Bearer", credentials=token)

    with pytest.raises(HTTPException) as exc_info:
        require_principal(credentials=creds)
    assert exc_info.value.status_code == 503
    assert "retry" in exc_info.value.detail.lower()


@pytest.mark.unit
def test_jwt_mode_unconfigured_returns_503(jwt_mode) -> None:
    """When no JWKS URL / issuer / audience is set, the dependency 503s.

    Unlike the original v0.9.0 stub, this is now driven by the real
    get_verifier() failing at construction time rather than a hardcoded
    response. Same external behaviour, real underlying logic.
    """
    settings = get_settings()
    saved = (settings.api_jwks_url, settings.api_jwt_issuer, settings.api_jwt_audience)
    settings.api_jwks_url = None
    settings.api_jwt_issuer = None
    settings.api_jwt_audience = None
    jwt_verifier_module.reset_verifier()
    try:
        creds = HTTPAuthorizationCredentials(scheme="Bearer", credentials="anything")
        with pytest.raises(HTTPException) as exc_info:
            require_principal(credentials=creds)
        assert exc_info.value.status_code == 503
        # The error names the missing settings so an operator can fix it.
        assert "api_jwks_url" in exc_info.value.detail
    finally:
        (
            settings.api_jwks_url,
            settings.api_jwt_issuer,
            settings.api_jwt_audience,
        ) = saved
