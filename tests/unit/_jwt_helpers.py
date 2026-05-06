"""Shared helpers for JWT verifier tests.

The helpers generate a fresh RSA keypair per test (cheap at 2048-bit;
slow only if many tests do it), expose the public key as a JWKS dict,
and mint tokens against the private key.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any
from uuid import UUID, uuid4

import httpx
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from jose import jwk, jwt


@dataclass(frozen=True)
class TestKeypair:
    """A test RSA keypair plus the JWKS document that publishes the public half."""

    private_pem: str
    jwks: dict[str, Any]
    kid: str

    def mint(
        self,
        *,
        sub: str | UUID | None = None,
        issuer: str = "https://test-issuer.example.com/",
        audience: str = "cascade-api",
        expires_in_seconds: int = 60,
        extra_claims: dict[str, Any] | None = None,
        kid: str | None = None,
        algorithm: str = "RS256",
    ) -> str:
        """Mint a JWT signed by this keypair.

        Defaults are convenient: a random sub, an issuer/audience that match
        the verifier built by :func:`make_verifier_with_keypair`, a 60s
        expiry. Pass ``extra_claims`` to override any individual field
        (including iss, aud, exp).
        """
        now = int(time.time())
        sub_str = str(sub) if sub is not None else str(uuid4())
        claims: dict[str, Any] = {
            "sub": sub_str,
            "iss": issuer,
            "aud": audience,
            "iat": now,
            "exp": now + expires_in_seconds,
        }
        if extra_claims:
            claims.update(extra_claims)
        return jwt.encode(
            claims,
            self.private_pem,
            algorithm=algorithm,
            headers={"kid": kid or self.kid},
        )


def make_keypair(*, kid: str = "test-kid-1") -> TestKeypair:
    """Generate a fresh RSA keypair and the matching single-key JWKS document."""
    priv_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    priv_pem = priv_key.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    ).decode()
    pub_pem = (
        priv_key.public_key()
        .public_bytes(
            serialization.Encoding.PEM,
            serialization.PublicFormat.SubjectPublicKeyInfo,
        )
        .decode()
    )
    pub_jwk = jwk.construct(pub_pem, algorithm="RS256").to_dict()
    pub_jwk["kid"] = kid
    pub_jwk["use"] = "sig"
    pub_jwk["alg"] = "RS256"
    # python-jose's to_dict() can return bytes for n/e fields — JSON serialisation
    # in the JWKS endpoint requires str, so coerce here.
    for field_name in ("n", "e"):
        if isinstance(pub_jwk.get(field_name), bytes):
            pub_jwk[field_name] = pub_jwk[field_name].decode()
    return TestKeypair(private_pem=priv_pem, jwks={"keys": [pub_jwk]}, kid=kid)


def jwks_transport(
    keypair: TestKeypair, *, jwks_url: str = "https://test-issuer.example.com/jwks.json"
) -> httpx.MockTransport:
    """Return an httpx transport that serves the keypair's JWKS at ``jwks_url``."""

    def handler(request: httpx.Request) -> httpx.Response:
        if str(request.url) == jwks_url:
            return httpx.Response(200, json=keypair.jwks)
        return httpx.Response(404, json={"detail": "not found"})

    return httpx.MockTransport(handler)


def jwks_failing_transport(*, status_code: int = 503) -> httpx.MockTransport:
    """Transport that always fails the JWKS fetch — for testing fail-closed paths."""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(status_code, json={"detail": "provider down"})

    return httpx.MockTransport(handler)
