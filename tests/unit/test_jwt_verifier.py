"""Tests for :class:`cascade.api.jwt_verifier.JWTVerifier`."""

from __future__ import annotations

import time
from uuid import uuid4

import httpx
import pytest

from cascade.api.auth import Principal
from cascade.api.jwt_verifier import (
    JWKSClient,
    JWKSUnavailable,
    JWTVerificationError,
    JWTVerifier,
)
from tests.unit._jwt_helpers import (
    jwks_failing_transport,
    jwks_transport,
    make_keypair,
)

JWKS_URL = "https://test-issuer.example.com/jwks.json"
ISSUER = "https://test-issuer.example.com/"
AUDIENCE = "cascade-api"


def _verifier_for(keypair, *, transport: httpx.MockTransport | None = None) -> JWTVerifier:
    client = JWKSClient(transport=transport or jwks_transport(keypair, jwks_url=JWKS_URL))
    return JWTVerifier(
        jwks_client=client,
        jwks_url=JWKS_URL,
        issuer=ISSUER,
        audience=AUDIENCE,
    )


# -- happy path ---------------------------------------------------------------


@pytest.mark.unit
def test_valid_token_returns_principal_with_sub_as_user_id() -> None:
    keypair = make_keypair()
    verifier = _verifier_for(keypair)
    user_id = uuid4()

    token = keypair.mint(sub=user_id, issuer=ISSUER, audience=AUDIENCE)
    principal = verifier.verify(token)

    assert isinstance(principal, Principal)
    assert principal.user_id == user_id


@pytest.mark.unit
def test_token_team_id_claim_populates_principal() -> None:
    keypair = make_keypair()
    verifier = _verifier_for(keypair)
    team_id = uuid4()

    token = keypair.mint(issuer=ISSUER, audience=AUDIENCE, extra_claims={"team_id": str(team_id)})
    principal = verifier.verify(token)
    assert principal.team_id == team_id


@pytest.mark.unit
def test_namespaced_team_id_claim_supported() -> None:
    """Auth0 and similar providers namespace custom claims; cascade reads either form."""
    keypair = make_keypair()
    verifier = _verifier_for(keypair)
    team_id = uuid4()

    token = keypair.mint(
        issuer=ISSUER,
        audience=AUDIENCE,
        extra_claims={"https://cascade/team_id": str(team_id)},
    )
    principal = verifier.verify(token)
    assert principal.team_id == team_id


@pytest.mark.unit
def test_malformed_team_id_is_treated_as_absent_not_failure() -> None:
    """A bad team_id claim shouldn't lock out an otherwise-valid principal."""
    keypair = make_keypair()
    verifier = _verifier_for(keypair)
    token = keypair.mint(issuer=ISSUER, audience=AUDIENCE, extra_claims={"team_id": "not-a-uuid"})
    principal = verifier.verify(token)
    assert principal.team_id is None


# -- expiration and timing ----------------------------------------------------


@pytest.mark.unit
def test_expired_token_raises_verification_error() -> None:
    keypair = make_keypair()
    verifier = _verifier_for(keypair)

    token = keypair.mint(issuer=ISSUER, audience=AUDIENCE, expires_in_seconds=-60)
    with pytest.raises(JWTVerificationError, match="expired"):
        verifier.verify(token)


@pytest.mark.unit
def test_clock_skew_within_leeway_passes() -> None:
    """A token that expired 5 seconds ago still verifies thanks to the 30s leeway."""
    keypair = make_keypair()
    verifier = _verifier_for(keypair)

    token = keypair.mint(issuer=ISSUER, audience=AUDIENCE, expires_in_seconds=-5)
    # Should not raise — the 30s default leeway absorbs the 5s skew.
    verifier.verify(token)


# -- claim validation ---------------------------------------------------------


@pytest.mark.unit
def test_wrong_issuer_raises_verification_error() -> None:
    keypair = make_keypair()
    verifier = _verifier_for(keypair)

    token = keypair.mint(issuer="https://wrong-issuer/", audience=AUDIENCE)
    with pytest.raises(JWTVerificationError):
        verifier.verify(token)


@pytest.mark.unit
def test_wrong_audience_raises_verification_error() -> None:
    keypair = make_keypair()
    verifier = _verifier_for(keypair)

    token = keypair.mint(issuer=ISSUER, audience="some-other-service")
    with pytest.raises(JWTVerificationError):
        verifier.verify(token)


@pytest.mark.unit
def test_missing_sub_claim_raises_verification_error() -> None:
    """A token without sub fails verification — either at python-jose's
    claim validation or at our own check. Either way we surface a
    :class:`JWTVerificationError`; the exact message is incidental."""
    keypair = make_keypair()
    verifier = _verifier_for(keypair)

    token = keypair.mint(
        issuer=ISSUER,
        audience=AUDIENCE,
        extra_claims={"sub": None},
    )
    with pytest.raises(JWTVerificationError):
        verifier.verify(token)


@pytest.mark.unit
def test_non_uuid_sub_raises_verification_error() -> None:
    keypair = make_keypair()
    verifier = _verifier_for(keypair)

    token = keypair.mint(issuer=ISSUER, audience=AUDIENCE, extra_claims={"sub": "user-12345"})
    with pytest.raises(JWTVerificationError, match="UUID"):
        verifier.verify(token)


# -- signature validation -----------------------------------------------------


@pytest.mark.unit
def test_token_signed_by_different_key_fails_verification() -> None:
    """Token minted by attacker's keypair is rejected even with matching kid."""
    real_keypair = make_keypair(kid="test-kid-1")
    attacker_keypair = make_keypair(kid="test-kid-1")  # same kid, different key

    verifier = _verifier_for(real_keypair)
    forged_token = attacker_keypair.mint(issuer=ISSUER, audience=AUDIENCE)

    with pytest.raises(JWTVerificationError):
        verifier.verify(forged_token)


@pytest.mark.unit
def test_token_with_unknown_kid_raises_verification_error() -> None:
    keypair = make_keypair(kid="known-kid")
    verifier = _verifier_for(keypair)

    token = keypair.mint(issuer=ISSUER, audience=AUDIENCE, kid="unknown-kid")
    with pytest.raises(JWTVerificationError, match="kid"):
        verifier.verify(token)


@pytest.mark.unit
def test_token_with_no_kid_header_raises_verification_error() -> None:
    """Even before signature check — no kid means we can't pick a key."""
    from jose import jwt as jose_jwt

    keypair = make_keypair()
    verifier = _verifier_for(keypair)

    # Mint without a kid header
    token_no_kid = jose_jwt.encode(
        {
            "sub": str(uuid4()),
            "iss": ISSUER,
            "aud": AUDIENCE,
            "iat": int(time.time()),
            "exp": int(time.time()) + 60,
        },
        keypair.private_pem,
        algorithm="RS256",
    )
    with pytest.raises(JWTVerificationError, match="kid"):
        verifier.verify(token_no_kid)


@pytest.mark.unit
def test_alg_none_token_is_rejected() -> None:
    """Defence in depth: refuse alg=none even before reaching python-jose."""
    keypair = make_keypair()
    verifier = _verifier_for(keypair)

    # Hand-construct an alg=none token (header + payload + empty sig).
    import base64

    header = (
        base64.urlsafe_b64encode(b'{"alg":"none","kid":"test-kid-1","typ":"JWT"}')
        .decode()
        .rstrip("=")
    )
    payload = (
        base64.urlsafe_b64encode(
            b'{"sub":"'
            + str(uuid4()).encode()
            + b'","iss":"'
            + ISSUER.encode()
            + b'","aud":"'
            + AUDIENCE.encode()
            + b'"}'
        )
        .decode()
        .rstrip("=")
    )
    forged = f"{header}.{payload}."

    with pytest.raises(JWTVerificationError, match="none"):
        verifier.verify(forged)


@pytest.mark.unit
def test_malformed_token_raises_verification_error() -> None:
    keypair = make_keypair()
    verifier = _verifier_for(keypair)

    with pytest.raises(JWTVerificationError):
        verifier.verify("this.is.not-a-jwt")


# -- JWKS unavailability ------------------------------------------------------


@pytest.mark.unit
def test_jwks_endpoint_5xx_raises_jwks_unavailable() -> None:
    """A provider outage is distinct from a verification failure."""
    keypair = make_keypair()
    verifier = JWTVerifier(
        jwks_client=JWKSClient(transport=jwks_failing_transport(status_code=503)),
        jwks_url=JWKS_URL,
        issuer=ISSUER,
        audience=AUDIENCE,
    )
    token = keypair.mint(issuer=ISSUER, audience=AUDIENCE)

    with pytest.raises(JWKSUnavailable):
        verifier.verify(token)


@pytest.mark.unit
def test_jwks_endpoint_returns_non_json_raises_jwks_unavailable() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=b"<html>oops</html>")

    keypair = make_keypair()
    verifier = JWTVerifier(
        jwks_client=JWKSClient(transport=httpx.MockTransport(handler)),
        jwks_url=JWKS_URL,
        issuer=ISSUER,
        audience=AUDIENCE,
    )
    token = keypair.mint(issuer=ISSUER, audience=AUDIENCE)

    with pytest.raises(JWKSUnavailable):
        verifier.verify(token)


@pytest.mark.unit
def test_jwks_endpoint_with_no_keyed_keys_raises() -> None:
    """A document with keys[] but no kid fields is unusable."""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"keys": [{"kty": "RSA"}]})

    keypair = make_keypair()
    verifier = JWTVerifier(
        jwks_client=JWKSClient(transport=httpx.MockTransport(handler)),
        jwks_url=JWKS_URL,
        issuer=ISSUER,
        audience=AUDIENCE,
    )
    token = keypair.mint(issuer=ISSUER, audience=AUDIENCE)

    with pytest.raises(JWKSUnavailable):
        verifier.verify(token)


# -- caching behaviour --------------------------------------------------------


@pytest.mark.unit
def test_jwks_cache_avoids_refetch_on_repeat_verify() -> None:
    """A second verify on a fresh token shouldn't trigger a second JWKS fetch."""
    keypair = make_keypair()
    fetch_count = 0

    def counting_handler(request: httpx.Request) -> httpx.Response:
        nonlocal fetch_count
        fetch_count += 1
        return httpx.Response(200, json=keypair.jwks)

    verifier = JWTVerifier(
        jwks_client=JWKSClient(transport=httpx.MockTransport(counting_handler)),
        jwks_url=JWKS_URL,
        issuer=ISSUER,
        audience=AUDIENCE,
    )

    for _ in range(5):
        token = keypair.mint(issuer=ISSUER, audience=AUDIENCE)
        verifier.verify(token)

    assert fetch_count == 1, (
        f"Expected one JWKS fetch across 5 verifies; got {fetch_count} — "
        "the cache isn't serving hits"
    )


@pytest.mark.unit
def test_jwks_cache_refetches_on_unknown_kid() -> None:
    """If the cached JWKS doesn't have the token's kid, we refetch once."""
    keypair_v1 = make_keypair(kid="kid-v1")
    keypair_v2 = make_keypair(kid="kid-v2")
    fetch_count = 0
    serve_v2 = False

    def rotating_handler(request: httpx.Request) -> httpx.Response:
        nonlocal fetch_count
        fetch_count += 1
        # First fetch returns v1; subsequent fetches return v2.
        return httpx.Response(200, json=keypair_v2.jwks if serve_v2 else keypair_v1.jwks)

    verifier = JWTVerifier(
        jwks_client=JWKSClient(transport=httpx.MockTransport(rotating_handler)),
        jwks_url=JWKS_URL,
        issuer=ISSUER,
        audience=AUDIENCE,
    )

    # Warm the cache with the v1 key
    verifier.verify(keypair_v1.mint(issuer=ISSUER, audience=AUDIENCE))
    fetches_after_warm = fetch_count

    # Now ask for a token signed by v2 — the kid won't be in the cache, so the
    # client should refetch.
    serve_v2 = True
    # We need the verifier to actually check the v2 token's signature, which
    # means the JWKS must contain the v2 key. The handler now serves v2's JWKS.
    verifier.verify(keypair_v2.mint(issuer=ISSUER, audience=AUDIENCE))
    assert fetch_count == fetches_after_warm + 1


# -- empty config -------------------------------------------------------------


@pytest.mark.unit
def test_verifier_construction_requires_url_issuer_audience() -> None:
    client = JWKSClient()
    with pytest.raises(ValueError, match="jwks_url"):
        JWTVerifier(jwks_client=client, jwks_url="", issuer=ISSUER, audience=AUDIENCE)
    with pytest.raises(ValueError, match="issuer"):
        JWTVerifier(jwks_client=client, jwks_url=JWKS_URL, issuer="", audience=AUDIENCE)
    with pytest.raises(ValueError, match="audience"):
        JWTVerifier(jwks_client=client, jwks_url=JWKS_URL, issuer=ISSUER, audience="")
