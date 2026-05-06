"""JWKS-backed JWT verification for the cascade REST API.

The shape of this module is intentionally provider-agnostic. Real-world
deployments point ``api_jwks_url`` at their identity provider's published
JWKS endpoint (Auth0, Clerk, AWS Cognito, Keycloak, Azure AD, ...) and set
``api_jwt_issuer`` and ``api_jwt_audience`` to match the tokens that
provider issues.

Composition:

- :class:`JWKSClient` — fetches the provider's JWKS document and caches the
  parsed keys with a TTL. Pluggable :class:`httpx.BaseTransport` so tests
  use :class:`httpx.MockTransport` to stub the network.
- :class:`JWTVerifier` — composes a :class:`JWKSClient` with the issuer +
  audience config and exposes :meth:`verify` that returns a
  :class:`Principal` or raises :class:`JWTVerificationError`.
- :func:`get_verifier` — module-level lazy singleton, built from
  :class:`Settings`. Dev-mode auth never instantiates the verifier so the
  JWKS endpoint is never reached during local development.

The verifier is **fail-closed by construction**: the :class:`Principal`
returned only carries identity claims that were actually verified. An
invalid signature, mismatched issuer, expired token, or unreachable JWKS
all raise :class:`JWTVerificationError` — no partial verification, no
silent demotion to a less-trusted principal.
"""

from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any
from uuid import UUID

import httpx
from cachetools import TTLCache
from jose import jwt
from jose.exceptions import (
    ExpiredSignatureError,
    JWKError,
    JWSError,
    JWTClaimsError,
    JWTError,
)

from cascade.config import get_settings

if TYPE_CHECKING:
    from cascade.api.auth import Principal

logger = logging.getLogger(__name__)


class JWTVerificationError(Exception):
    """Raised when a token can be parsed but fails any verification check."""


class JWKSUnavailable(Exception):  # noqa: N818 — not an "Error" because it's a service problem, not a user problem
    """Raised when the JWKS endpoint can't be reached.

    Distinguished from :class:`JWTVerificationError` because the right
    response is different: a verification failure is the user's problem
    (401), but a JWKS fetch failure is the service's problem (503 — try
    again).
    """


# -- JWKS client --------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class _CachedJWKS:
    """A JWKS document parsed into a kid → key mapping."""

    keys_by_kid: dict[str, dict[str, Any]]
    fetched_at: float


class JWKSClient:
    """Fetches and caches a JWKS document.

    The cache is keyed by JWKS URL so a single client can serve multiple
    providers if needed. TTL defaults to one hour — short enough that key
    rotations don't strand the service for long, long enough that a 100-rps
    workload doesn't hammer the provider.

    On a cache miss for a kid, the client refetches the JWKS once before
    raising. This handles the common case where the provider rotated keys
    between cache fills.
    """

    def __init__(
        self,
        *,
        cache_ttl_seconds: int = 3600,
        transport: httpx.BaseTransport | None = None,
        timeout_seconds: float = 5.0,
    ) -> None:
        self._cache: TTLCache[str, _CachedJWKS] = TTLCache(maxsize=8, ttl=cache_ttl_seconds)
        self._lock = threading.Lock()
        self._transport = transport
        self._timeout_seconds = timeout_seconds

    def get_signing_key(self, *, jwks_url: str, kid: str) -> dict[str, Any]:
        """Return the JWK matching ``kid``, refetching once on cache miss.

        Raises:
            JWTVerificationError: If the kid isn't present after a refetch
                (the token was signed with a key the provider isn't
                advertising — unrecoverable from the verifier's side).
            JWKSUnavailable: If the JWKS fetch failed.
        """
        cached = self._cache.get(jwks_url)
        if cached is not None and kid in cached.keys_by_kid:
            return cached.keys_by_kid[kid]

        # Either the cache is empty for this URL, or the kid isn't in the
        # cached document — refetch and retry once.
        with self._lock:
            cached = self._cache.get(jwks_url)
            if cached is None or kid not in cached.keys_by_kid:
                cached = self._fetch(jwks_url)
                self._cache[jwks_url] = cached

        key = cached.keys_by_kid.get(kid)
        if key is None:
            raise JWTVerificationError(
                f"Token's kid {kid!r} is not present in the JWKS at {jwks_url}. "
                "The token may have been signed with a rotated-out key, or with "
                "a key from a different provider."
            )
        return key

    def _fetch(self, jwks_url: str) -> _CachedJWKS:
        try:
            with httpx.Client(transport=self._transport, timeout=self._timeout_seconds) as client:
                response = client.get(jwks_url)
                response.raise_for_status()
                payload = response.json()
        except httpx.RequestError as exc:
            raise JWKSUnavailable(f"Could not reach JWKS endpoint {jwks_url}: {exc}") from exc
        except httpx.HTTPStatusError as exc:
            raise JWKSUnavailable(
                f"JWKS endpoint {jwks_url} returned {exc.response.status_code}"
            ) from exc
        except ValueError as exc:
            raise JWKSUnavailable(f"JWKS endpoint {jwks_url} returned non-JSON content") from exc

        keys = payload.get("keys")
        if not isinstance(keys, list):
            raise JWKSUnavailable(
                f"JWKS endpoint {jwks_url} returned a document without a 'keys' array"
            )

        keys_by_kid: dict[str, dict[str, Any]] = {}
        for key in keys:
            kid = key.get("kid")
            if isinstance(kid, str):
                keys_by_kid[kid] = key

        if not keys_by_kid:
            raise JWKSUnavailable(f"JWKS endpoint {jwks_url} returned no keys with a 'kid' field")

        return _CachedJWKS(keys_by_kid=keys_by_kid, fetched_at=time.time())

    def invalidate(self, jwks_url: str | None = None) -> None:
        """Drop a cached JWKS — for tests or for explicit refresh on rotation."""
        if jwks_url is None:
            self._cache.clear()
        else:
            self._cache.pop(jwks_url, None)


# -- verifier -----------------------------------------------------------------


class JWTVerifier:
    """Verifies a token against a configured issuer, audience, and JWKS."""

    def __init__(
        self,
        *,
        jwks_client: JWKSClient,
        jwks_url: str,
        issuer: str,
        audience: str,
        leeway_seconds: int = 30,
    ) -> None:
        if not jwks_url:
            raise ValueError("jwks_url is required")
        if not issuer:
            raise ValueError("issuer is required")
        if not audience:
            raise ValueError("audience is required")
        self._jwks_client = jwks_client
        self._jwks_url = jwks_url
        self._issuer = issuer
        self._audience = audience
        self._leeway_seconds = leeway_seconds

    def verify(self, token: str) -> Principal:
        """Verify ``token`` and return a :class:`Principal`.

        Raises:
            JWTVerificationError: For any verification failure (bad
                signature, expired, wrong issuer or audience, missing
                ``sub``, unparseable token, kid not in JWKS).
            JWKSUnavailable: If the JWKS endpoint can't be reached. Callers
                should map this to a 503 because the right action is to
                retry once the provider is back up.
        """
        from cascade.api.auth import Principal  # lazy to avoid a cycle

        try:
            unverified_header = jwt.get_unverified_header(token)
        except JWTError as exc:
            raise JWTVerificationError(f"Token header is malformed: {exc}") from exc

        kid = unverified_header.get("kid")
        if not isinstance(kid, str):
            raise JWTVerificationError(
                "Token header has no 'kid' claim — JWKS-based verification "
                "requires it to identify which key signed the token"
            )

        algorithm = unverified_header.get("alg")
        if not isinstance(algorithm, str):
            raise JWTVerificationError("Token header has no 'alg' claim")
        if algorithm == "none":
            # 'none' is rejected unconditionally even though python-jose
            # also rejects it — defence in depth against a regression in
            # the upstream library.
            raise JWTVerificationError("Tokens signed with alg=none are rejected")

        signing_key = self._jwks_client.get_signing_key(jwks_url=self._jwks_url, kid=kid)

        try:
            claims = jwt.decode(
                token,
                signing_key,
                algorithms=[algorithm],
                audience=self._audience,
                issuer=self._issuer,
                options={"leeway": self._leeway_seconds},
            )
        except ExpiredSignatureError as exc:
            raise JWTVerificationError("Token has expired") from exc
        except JWTClaimsError as exc:
            raise JWTVerificationError(f"Token claims invalid: {exc}") from exc
        except (JWSError, JWKError, JWTError) as exc:
            raise JWTVerificationError(f"Token signature invalid: {exc}") from exc

        sub = claims.get("sub")
        if not isinstance(sub, str):
            raise JWTVerificationError("Token has no 'sub' claim — cannot identify the principal")
        try:
            user_id = UUID(sub)
        except ValueError as exc:
            raise JWTVerificationError(
                "Token 'sub' is not a UUID. cascade expects sub to carry the "
                "user id; configure your provider to use the user's UUID as "
                "the subject claim, or implement a sub→user_id resolver."
            ) from exc

        team_id_claim = claims.get("team_id") or claims.get("https://cascade/team_id")
        team_id: UUID | None = None
        if isinstance(team_id_claim, str):
            try:
                team_id = UUID(team_id_claim)
            except ValueError:
                # A malformed team_id is logged and treated as absent rather
                # than failing verification. The principal is still valid;
                # team-scoped routes will simply require the user to pass
                # team_id explicitly.
                logger.warning("Token 'team_id' claim is not a UUID; ignoring (sub=%s)", sub)

        return Principal(user_id=user_id, team_id=team_id)


# -- module-level singleton ---------------------------------------------------

_verifier: JWTVerifier | None = None
_verifier_lock = threading.Lock()


def get_verifier() -> JWTVerifier:
    """Return the configured :class:`JWTVerifier`, building it lazily.

    Raises :class:`JWTVerificationError` (which the auth dependency maps to
    a 503) if any of ``api_jwks_url``, ``api_jwt_issuer``, or
    ``api_jwt_audience`` is missing — there's no safe default for any of
    those, so the right behaviour is to fail closed and surface the
    misconfiguration immediately.
    """
    global _verifier
    if _verifier is not None:
        return _verifier
    with _verifier_lock:
        if _verifier is not None:
            return _verifier

        settings = get_settings()
        if (
            not settings.api_jwks_url
            or not settings.api_jwt_issuer
            or not settings.api_jwt_audience
        ):
            raise JWTVerificationError(
                "JWT verification requires api_jwks_url, api_jwt_issuer, and "
                "api_jwt_audience to be configured. Set CASCADE_API_JWKS_URL, "
                "CASCADE_API_JWT_ISSUER, and CASCADE_API_JWT_AUDIENCE in the "
                "environment, or set CASCADE_API_AUTH_MODE=dev for development."
            )

        client = JWKSClient(cache_ttl_seconds=settings.api_jwks_cache_ttl_seconds)
        _verifier = JWTVerifier(
            jwks_client=client,
            jwks_url=settings.api_jwks_url,
            issuer=settings.api_jwt_issuer,
            audience=settings.api_jwt_audience,
        )
        return _verifier


def reset_verifier() -> None:
    """Drop the cached verifier — for tests, or for runtime reconfiguration."""
    global _verifier
    with _verifier_lock:
        _verifier = None


__all__ = [
    "JWKSClient",
    "JWKSUnavailable",
    "JWTVerificationError",
    "JWTVerifier",
    "get_verifier",
    "reset_verifier",
]
