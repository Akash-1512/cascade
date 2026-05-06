# JWT authentication

cascade verifies JWT bearer tokens against any provider that publishes a
standard JWKS endpoint. This runbook covers the configuration shape and the
specific values for the four most common providers.

## Configuration shape

Three environment variables enable JWT verification:

| Variable | Purpose |
|---|---|
| `CASCADE_API_AUTH_MODE=jwt` | Switch from dev-mode to JWT-mode |
| `CASCADE_API_JWKS_URL` | The provider's JWKS endpoint |
| `CASCADE_API_JWT_ISSUER` | Expected `iss` claim |
| `CASCADE_API_JWT_AUDIENCE` | Expected `aud` claim |

Optional:

| Variable | Default | Purpose |
|---|---|---|
| `CASCADE_API_JWKS_CACHE_TTL_SECONDS` | `3600` | TTL of the JWKS cache. Drop if your provider rotates keys faster than this. |

The verifier expects:

- **`sub`** is the user's UUID (cascade uses UUID identifiers internally — see "sub mapping" below if your provider uses something else)
- **`team_id`** or **`https://cascade/team_id`** optionally carries the user's home team UUID

If a token is missing `sub` or `sub` is not a UUID, verification fails with 401.

## Provider configurations

### Auth0

Auth0 publishes JWKS at `https://{tenant}.auth0.com/.well-known/jwks.json`.

```bash
export CASCADE_API_AUTH_MODE=jwt
export CASCADE_API_JWKS_URL="https://your-tenant.auth0.com/.well-known/jwks.json"
export CASCADE_API_JWT_ISSUER="https://your-tenant.auth0.com/"
export CASCADE_API_JWT_AUDIENCE="https://cascade.your-domain.com"
```

The trailing slash on `iss` matters. Auth0 includes it; verification fails if your
config drops it.

For custom claims like `team_id`, configure an Auth0 Action/Rule that namespaces
them, e.g. `https://cascade/team_id`. The verifier reads either `team_id` or the
namespaced form.

### AWS Cognito

```bash
export CASCADE_API_AUTH_MODE=jwt
export CASCADE_API_JWKS_URL="https://cognito-idp.{region}.amazonaws.com/{user_pool_id}/.well-known/jwks.json"
export CASCADE_API_JWT_ISSUER="https://cognito-idp.{region}.amazonaws.com/{user_pool_id}"
export CASCADE_API_JWT_AUDIENCE="{cognito_app_client_id}"
```

Cognito issues two token types: ID tokens (where `aud` is the app client id) and
Access tokens (where `aud` is missing and `client_id` carries the same value).
**Use ID tokens for cascade** — the verifier requires `aud`.

### Clerk

```bash
export CASCADE_API_AUTH_MODE=jwt
export CASCADE_API_JWKS_URL="https://{your-domain}.clerk.accounts.dev/.well-known/jwks.json"
export CASCADE_API_JWT_ISSUER="https://{your-domain}.clerk.accounts.dev"
export CASCADE_API_JWT_AUDIENCE="{your_clerk_frontend_api_url}"
```

Clerk's default `sub` is `user_xxxxxxxxxxxxx`, not a UUID. Configure a [JWT
template](https://clerk.com/docs/backend-requests/jwt-templates) with `{{user.id}}`
mapped to a UUID custom field, or implement a `sub`→`user_id` resolver
(see "sub mapping" below).

### Keycloak

```bash
export CASCADE_API_AUTH_MODE=jwt
export CASCADE_API_JWKS_URL="https://{keycloak}/realms/{realm}/protocol/openid-connect/certs"
export CASCADE_API_JWT_ISSUER="https://{keycloak}/realms/{realm}"
export CASCADE_API_JWT_AUDIENCE="cascade-api"
```

Keycloak's `sub` is a UUID by default. No mapping needed.

## sub mapping

If your identity provider's `sub` is not a UUID (Clerk's `user_xxx`, Cognito's
`{username}` with no UUID coercion, etc.), three options:

1. **Configure a custom claim** that carries the UUID and modify
   `cascade.api.jwt_verifier.JWTVerifier.verify` to read it instead of `sub`.
2. **Add a sub→user lookup** that resolves the provider's id to the local user
   id at the auth dependency boundary. Add a database call to
   `_resolve_jwt_token` after verification succeeds.
3. **Migrate user ids** to match the provider's format. cascade's User table
   uses UUID primary keys today; switching would require a migration.

Option 1 is the cleanest if you control the provider's claim shape.

## Security notes

- Tokens with `alg=none` are rejected unconditionally, before reaching
  python-jose's verifier. Defence in depth.
- The verifier returns the same generic error message for every verification
  failure (401 with detail "Token is invalid or expired"). This avoids
  leaking information that would help an attacker probe the verifier — they
  can't tell "expired" from "wrong audience" from "bad signature" by varying
  the token.
- The full verification reason is logged at INFO level on every failure for
  diagnosis.
- The JWKS cache uses a TTL, not "until invalidated" — even if your provider
  rotates keys without notice, traffic stops failing within `CASCADE_API_JWKS_CACHE_TTL_SECONDS`.
- On a token with a `kid` not in the cached JWKS, the verifier refetches the
  JWKS once before failing. This handles between-cache-fill key rotations
  without operator intervention.

## Troubleshooting

**`401 Token is invalid or expired`** — check the server log for the actual
verification reason. The 401 detail is intentionally generic.

**`503 Identity provider's JWKS endpoint is unavailable`** — the provider's
JWKS endpoint is down or unreachable from cascade's network. Check the
provider's status page; try `curl $CASCADE_API_JWKS_URL` from cascade's host.

**`503 JWT verification requires api_jwks_url, api_jwt_issuer, and
api_jwt_audience`** — one or more env vars is missing. Set all three or
switch to dev mode (`CASCADE_API_AUTH_MODE=dev`).

**Verification works locally but fails in production** — the most common
cause is `iss` drift: providers care about trailing slashes and the
exact host. Confirm the issuer in your config matches what the provider
puts in `iss` exactly. Decode a real token at https://jwt.io and compare.

**Tokens work for a while, then start failing** — your JWKS cache TTL is
longer than the provider's key rotation interval. Drop
`CASCADE_API_JWKS_CACHE_TTL_SECONDS` to a few minutes. The verifier will
refetch on cache miss anyway, so this is a soft tuning, not a correctness
issue.
