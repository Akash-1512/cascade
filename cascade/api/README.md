# cascade.api

Read-side REST API. Mutations flow through :mod:`cascade.mcp` because that's
where the agent loop lives.

## Routes

| Method | Path | Purpose |
|---|---|---|
| `GET` | `/health` | Liveness probe |
| `GET` | `/health/ready` | Readiness probe (checks Postgres) |
| `GET` | `/v1/teams/{team_id}/okrs` | List OKRs for a team |
| `GET` | `/v1/okrs/{id}` | Full OKR view with KRs |
| `GET` | `/v1/okrs/{id}/score` | Per-KR scoring breakdown |
| `GET` | `/v1/okrs/{id}/decisions` | Causal trail for an OKR |
| `GET` | `/v1/teams/{team_id}/learnings` | Organizational learning themes |

OpenAPI docs at `/docs`. The schema lives at `/openapi.json` and is the
authoritative interface contract — generated clients should regenerate when
this changes.

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
- **`api_auth_mode=jwt`** — production. Real provider integration (Auth0,
  Clerk, Cognito, ...) is the deployment's responsibility. Until wired in,
  the dependency returns 503 — failing closed surfaces misconfiguration
  immediately.

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
