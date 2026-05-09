# REST API

cascade exposes a REST API alongside the MCP server. Read endpoints for
OKRs, decisions, and organizational learnings; mutation endpoints for
committing aligned drafts, logging decisions and check-ins, and recording
learnings. Mid-life agent-driven mutations (target changes, draft
pause-and-resume, risk interventions) still flow through MCP because they
involve the agent loop — what's exposed over REST is pure persistence.

## Routes

### Read

| Method | Path | Purpose |
|---|---|---|
| `GET` | `/health` | Liveness probe |
| `GET` | `/health/ready` | Readiness probe (checks Postgres) |
| `GET` | `/v1/teams/{team_id}/okrs?quarter={q}` | List OKRs |
| `GET` | `/v1/okrs/{id}` | Full OKR view |
| `GET` | `/v1/okrs/{id}/score` | Score breakdown |
| `GET` | `/v1/okrs/{id}/decisions?limit={n}` | Causal trail |
| `GET` | `/v1/teams/{team_id}/learnings?quarter={q}&category={c}` | Org learnings |

### Mutations (added in v0.14.0)

| Method | Path | Purpose |
|---|---|---|
| `POST` | `/v1/teams/{team_id}/okrs` | Commit an Objective from an aligned draft |
| `POST` | `/v1/okrs/{id}/decisions` | Log a Decision against an Objective |
| `POST` | `/v1/key-results/{id}/checkins` | Log a CheckIn against a Key Result |
| `POST` | `/v1/teams/{team_id}/learnings` | Record an organizational learning |

All POST endpoints return 201 with the canonical resource body and a
`Location` header pointing at the GET path. 404 for missing parent
resources (team, OKR, KR, parent OKR). 422 for malformed UUIDs or
constraint violations.

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

### Commit an Objective from an aligned draft

```bash
curl -X POST http://localhost:8000/v1/teams/2f3e1c4a-.../okrs \
  -H "Authorization: Bearer $(uuidgen)" \
  -H "Content-Type: application/json" \
  -d '{
    "title": "Reach product-market fit in the SMB segment",
    "description": "Convert Q1 enterprise pilot insights into an SMB push",
    "quarter": "2026Q2",
    "owner_id": "11111111-1111-1111-1111-111111111111",
    "key_results": [
      {
        "description": "Lift weekly active accounts from 200 to 800",
        "metric_type": "number",
        "baseline_value": 200,
        "target_value": 800,
        "current_value": 200,
        "unit": "accounts",
        "weight": 0.5
      },
      {
        "description": "Move trial-to-paid conversion from 6% to 14%",
        "metric_type": "percentage",
        "baseline_value": 6,
        "target_value": 14,
        "current_value": 6,
        "weight": 0.5
      }
    ]
  }'
```

Returns 201 with the canonical Objective shape (including the assigned
`id`) and a `Location: /v1/okrs/{id}` header. Typical flow: a HITL draft
on the MCP side completes, the agent returns an aligned proposal, then a
script POSTs that proposal here to commit it.

### Log a Decision

```bash
curl -X POST http://localhost:8000/v1/okrs/9b7d8a2e-.../decisions \
  -H "Authorization: Bearer 11111111-1111-1111-1111-111111111111" \
  -H "Content-Type: application/json" \
  -d '{
    "event_type": "kr_target_change",
    "summary": "Lowered trial-to-paid target from 18% to 14% after pricing audit",
    "chosen": "14% conversion target",
    "tradeoff": "Less ambitious headline number, but no longer requires a price change we have not approved",
    "alternatives": [
      {
        "option": "Keep the 18% target",
        "reason_rejected": "Finance pushed back: 18% requires either a price cut or a free-trial extension we cannot fund this quarter"
      }
    ],
    "evidence": [
      {"source": "Pricing model v3", "claim": "18% conversion at current price implies negative gross margin"}
    ]
  }'
```

`actor_id` defaults to the principal's user_id. Override it in the body
when a service account logs a decision on behalf of a real user.

### Log a CheckIn

```bash
curl -X POST http://localhost:8000/v1/key-results/4f8d2a1c-.../checkins \
  -H "Authorization: Bearer 11111111-1111-1111-1111-111111111111" \
  -H "Content-Type: application/json" \
  -d '{
    "progress_value": 480,
    "confidence": "medium",
    "narrative": "Halfway to target but conversion lagging — see decision attached for the lowered target"
  }'
```

Without `new_status`, the persisted status is derived from `confidence`
(high → on_track, medium → at_risk, low → off_track). Pass `new_status`
explicitly to override (useful when numbers look fine but you're reading a
structural risk that confidence alone doesn't capture).

### Record an organizational learning

```bash
curl -X POST http://localhost:8000/v1/teams/2f3e1c4a-.../learnings \
  -H "Authorization: Bearer $(uuidgen)" \
  -H "Content-Type: application/json" \
  -d '{
    "quarter": "2026Q1",
    "title": "Underestimated CSM adoption friction on data products",
    "description": "Three Q1 OKRs shipped technically-correct work that the CSM team did not end up using. Pattern indicates a missing operator-adoption KR on data product OKRs going forward.",
    "category": "alignment",
    "occurrences": 3
  }'
```

Pass `supersedes_id` to link the new learning to the previous version it
replaces — the audit trail keeps the predecessor; nothing is destructively
overwritten.

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
