# cascade.api

REST API. Read endpoints for OKRs, decisions, and organizational learnings;
mutation endpoints for committing aligned drafts, logging decisions and
check-ins, and recording learnings. Mid-life agent-driven mutations (target
changes, draft pause-and-resume) still flow through MCP because they
involve the agent loop — what's exposed here is pure persistence.

## Routes

### Read

| Method | Path | Purpose |
|---|---|---|
| `GET` | `/health` | Liveness probe |
| `GET` | `/health/ready` | Readiness probe (checks Postgres) |
| `GET` | `/v1/teams/{team_id}/okrs` | List OKRs for a team |
| `GET` | `/v1/okrs/{id}` | Full OKR view with KRs |
| `GET` | `/v1/okrs/{id}/score` | Per-KR scoring breakdown |
| `GET` | `/v1/okrs/{id}/decisions` | Causal trail for an OKR |
| `GET` | `/v1/teams/{team_id}/learnings` | Organizational learning themes |

### Mutations (added in v0.14.0)

| Method | Path | Purpose |
|---|---|---|
| `POST` | `/v1/teams/{team_id}/okrs` | Create an Objective from an aligned draft |
| `POST` | `/v1/okrs/{id}/decisions` | Log a Decision against an Objective |
| `POST` | `/v1/key-results/{id}/checkins` | Log a CheckIn against a Key Result |
| `POST` | `/v1/teams/{team_id}/learnings` | Record an organizational learning |

All POST endpoints return 201 on success with the canonical resource shape
in the body and a `Location` header pointing at the GET path. 404 for
missing parent resources (team, OKR, KR, parent OKR). 422 for malformed
UUIDs or constraint violations (KR weight out of range, quarter format).

OpenAPI docs at `/docs`. The schema lives at `/openapi.json` and is the
authoritative interface contract — generated clients should regenerate when
this changes.

## Why the read/mutate split

Read endpoints are unconditional — any authenticated principal can hit
them. Mutation endpoints fall into two buckets:

- **Pure persistence** (POST endpoints in this module). The client already
  knows what it wants to write — an aligned draft from a HITL flow, a
  decision recorded after a meeting, a check-in result from a sprint demo.
  REST is the right shape: idempotent in spirit, scriptable from CI,
  loggable through standard HTTP infrastructure.
- **Agent-driven mutations** (target changes, draft pause-and-resume,
  risk interventions). The client needs the agent loop to evaluate state
  before persisting. These flow through MCP where the loop lives.

The split is **not** a layer boundary — both REST POSTs and MCP tools
ultimately call the same domain repositories. It's a usage-pattern
boundary: REST when the caller knows the answer, MCP when the agent does.

## Files

```
api/
├── __init__.py        Public API
├── main.py            FastAPI app construction; lifespan; CORS; route mounting
├── auth.py            Principal + require_principal dependency
├── dependencies.py    SessionDep — async session per request
├── schemas.py         Wire-format Pydantic types (distinct from MCP)
└── routes/
    ├── __init__.py
    ├── okrs.py        GET /v1/teams/{team_id}/okrs, /v1/okrs/{id}, /v1/okrs/{id}/score
    ├── decisions.py   GET /v1/okrs/{id}/decisions
    └── learnings.py   GET /v1/teams/{team_id}/learnings
```

## Auth

Bearer token via the `Authorization` header. Two modes:

- **`api_auth_mode=dev`** — any UUID is accepted as the principal's `user_id`.
  Useful for curl, the Streamlit operator console, and any local development.
- **`api_auth_mode=jwt`** — production. Verifies tokens against any provider
  publishing a standard JWKS document (Auth0, AWS Cognito, Clerk, Keycloak,
  Azure AD, ...). JWKS is fetched on first use and TTL-cached. Configure
  via `CASCADE_API_JWKS_URL`, `CASCADE_API_JWT_ISSUER`,
  `CASCADE_API_JWT_AUDIENCE`. See [`docs/runbooks/jwt-auth.md`](../../docs/runbooks/jwt-auth.md)
  for provider-specific setup.

Without configuration, JWT mode fails closed with a 503 that names the
missing settings. Verification failures (expired, wrong issuer, bad
signature, etc.) all return the same generic 401 — the specific reason is
logged at INFO level, but never leaked to the caller.

Routes opt into auth via the dependency — the requirement shows up in the
generated OpenAPI document automatically.

```python
async def get_okr(
    objective_id: UUID,
    session: SessionDep,
    principal: Annotated[Principal, Depends(require_principal)],
) -> ObjectiveResponse:
    ...
```

## Wire schemas separate from MCP

`cascade.api.schemas` is intentionally distinct from `cascade.mcp.schemas`.
The two surfaces evolve independently — adding a field to the REST API
shouldn't force a corresponding change to the MCP tool surface, and a
breaking change to one shouldn't ripple through the other.

Both surfaces translate the same domain types into the same general shape
(UUIDs as strings, datetimes as ISO 8601, nested types flattened to dicts),
but they own their own contracts.

## Why read-only

Mutations to OKR state happen through the agent loop — drafting goes through
the Drafter→Critic→Aligner LangGraph; check-ins go through the Coach;
target changes are decisions captured by the recorder. Exposing direct
mutation endpoints would create two paths into the same state, and the
non-agent path would skip the governance the agent path provides (Critic
gating, Decision capture, OrganizationalLearning persistence).

The MCP server is the single mutation surface. The REST API exposes reads
plus convenience accessors. When the Streamlit UI lands, it'll use this API
for reads and the MCP server (over a shared service binding) for writes.

## Running locally

```bash
uvicorn cascade.api.main:app --reload --host 0.0.0.0 --port 8000
```

```bash
# List OKRs (replace UUIDs with real ones)
curl http://localhost:8000/v1/teams/$TEAM_ID/okrs \
  -H "Authorization: Bearer $(uuidgen)"

# Get one OKR with KRs
curl http://localhost:8000/v1/okrs/$OKR_ID \
  -H "Authorization: Bearer $(uuidgen)"

# Get the causal trail
curl http://localhost:8000/v1/okrs/$OKR_ID/decisions \
  -H "Authorization: Bearer $(uuidgen)"
```

## Testing

- `tests/unit/test_api_auth.py` — 5 tests on the auth dependency
- `tests/integration/test_api_routes.py` — 13 tests using FastAPI's
  `TestClient` with the database dependency overridden to use the test
  SQLite engine

The tests dependency-override `get_session` to use the integration test
engine. Production routes pull the sessionmaker from
`get_sessionmaker()` which respects `DATABASE_URL`.

## See also

- [MCP server](../mcp/README.md)
- [Storage layer](../storage/repositories/)
- [API runbook](../../docs/runbooks/rest-api.md)
