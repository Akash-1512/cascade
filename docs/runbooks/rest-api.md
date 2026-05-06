# REST API

cascade exposes a read-side REST API as the second integration surface
alongside the MCP server. Mutations flow through MCP because that's where the
agent loop lives; the REST API is for read access — list views, OKR details,
causal trails, and organizational learnings.

## Routes

| Method | Path | Purpose |
|---|---|---|
| `GET` | `/health` | Liveness probe |
| `GET` | `/health/ready` | Readiness probe (checks Postgres) |
| `GET` | `/v1/teams/{team_id}/okrs?quarter={q}` | List OKRs |
| `GET` | `/v1/okrs/{id}` | Full OKR view |
| `GET` | `/v1/okrs/{id}/score` | Score breakdown |
| `GET` | `/v1/okrs/{id}/decisions?limit={n}` | Causal trail |
| `GET` | `/v1/teams/{team_id}/learnings?quarter={q}&category={c}` | Org learnings |

Full schema at `/openapi.json` and `/docs`.

## Running locally

```bash
# Bring up the database first
docker compose up -d postgres
alembic upgrade head

# Serve the API
uvicorn cascade.api.main:app --reload --host 0.0.0.0 --port 8000
```

The server reads `DATABASE_URL` and `CASCADE_API_AUTH_MODE` from environment
or `.env`. Defaults are sensible for local development.

## Authentication

```bash
# Dev mode: any UUID is accepted
curl http://localhost:8000/v1/teams/$TEAM_ID/okrs \
  -H "Authorization: Bearer $(uuidgen)"
```

Set `CASCADE_API_AUTH_MODE=dev` (the default) for development. For
production, wire a real JWKS verifier in `cascade.api.auth._resolve_jwt_token`
and set `CASCADE_API_AUTH_MODE=jwt`.

## CORS

Configurable via `CASCADE_API_CORS_ALLOW_ORIGINS` (a JSON array). Defaults to
`["*"]`. Tighten this in production:

```bash
export CASCADE_API_CORS_ALLOW_ORIGINS='["https://cascade.your-domain.com"]'
```

## Examples

### List a team's OKRs for a specific quarter

```bash
curl 'http://localhost:8000/v1/teams/2f3e1c4a-.../okrs?quarter=2026Q2' \
  -H "Authorization: Bearer $(uuidgen)"
```

```json
{
  "items": [
    {
      "id": "9b7d8a2e-...",
      "title": "Reach product-market fit in the SMB segment",
      "quarter": "2026Q2",
      "status": "active",
      "score": 0.5
    }
  ],
  "count": 1
}
```

### Get an OKR with KRs and derived scores

```bash
curl http://localhost:8000/v1/okrs/9b7d8a2e-... \
  -H "Authorization: Bearer $(uuidgen)"
```

```json
{
  "id": "9b7d8a2e-...",
  "title": "Reach product-market fit in the SMB segment",
  "description": "Q2 focus on SMB conversion",
  "quarter": "2026Q2",
  "status": "active",
  "team_id": "2f3e1c4a-...",
  "owner_id": "...",
  "parent_objective_id": null,
  "score": 0.5,
  "key_results": [
    {
      "id": "...",
      "description": "Lift weekly active accounts from 200 to 800",
      "metric_type": "number",
      "baseline_value": 200,
      "target_value": 800,
      "current_value": 500,
      "unit": "accounts",
      "weight": 1.0,
      "status": "on_track",
      "score": 0.5
    }
  ],
  "created_at": "2026-04-01T...",
  "updated_at": "2026-05-06T..."
}
```

### Get the causal trail

```bash
curl http://localhost:8000/v1/okrs/9b7d8a2e-.../decisions \
  -H "Authorization: Bearer $(uuidgen)"
```

Returns every state-changing decision: commits, target changes, descopes,
each with the alternatives considered, the chosen option, and the tradeoff
accepted. This is what powers the "why was this lowered last quarter" query.

### List organizational learnings

```bash
curl 'http://localhost:8000/v1/teams/2f3e1c4a-.../learnings?category=estimation' \
  -H "Authorization: Bearer $(uuidgen)"
```

Returns the team's running list of estimation-related learnings across
quarters. Filter by `quarter` to see what was distilled in a specific
retrospective.

## Pagination

The API uses simple list responses with a `count` field. Cursor-based
pagination will land when any list response exceeds practical sizes (50 OKRs
per team per quarter is fine; 500 decisions on a single OKR is rare). Until
then, `limit` query parameters cap response sizes.

## Troubleshooting

**`401 Unauthorized` from a route that worked yesterday.** Check
`CASCADE_API_AUTH_MODE` — production deployments fail closed without a
configured JWKS verifier. Use `dev` mode for local testing.

**`503 Service Unavailable` from `/health/ready`.** Postgres is unreachable.
Liveness (`/health`) does not depend on the database — it returns 200 even
when Postgres is down — so use that for liveness probes.

**`422 Unprocessable Entity` on `?quarter=...`.** Quarters must match
`YYYYQ[1-4]` exactly. `2026q2` (lowercase) and `2026-Q2` are both rejected.
