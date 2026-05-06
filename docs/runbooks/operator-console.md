# Operator console

Streamlit-based read-only viewer for cascade. Run alongside the REST API
to give a non-MCP audience access to OKRs, decision trails, and
organizational learnings.

## Running locally

```bash
# Bring up Postgres
docker compose up -d postgres
alembic upgrade head

# Run the REST API
uvicorn cascade.api.main:app --host 0.0.0.0 --port 8000 &

# Run the console
streamlit run cascade/ui/app.py
```

Streamlit prints the URL (typically `http://localhost:8501`). Open it.

## Sidebar configuration

The sidebar carries everything the console needs:

| Field | Description | Default |
|---|---|---|
| API URL | Base URL of the cascade REST API | `http://localhost:8000` |
| Bearer token | Dev mode: any UUID. Production: real JWT. | empty |
| Team ID | UUID of the team to view | empty |
| Quarter | One of the recent quarters or "All" | current quarter |
| View | OKR list / OKR detail / Learnings | OKR list |

Environment overrides:

- `CASCADE_UI_API_URL` — defaults the API URL field
- `CASCADE_UI_BEARER_TOKEN` — defaults the bearer token field

The "Connection status" panel in the sidebar runs `/health` on every
render. If you see `:red-badge[unreachable]`, the API isn't running or the
URL is wrong.

## Three views

### OKR list

Sortable table of OKRs for the selected team and quarter. Columns: short
ID, title, quarter, status, score. The score and status columns use the
shared visual vocabulary — green/orange/red coding that matches what the
Risk Sentinel emits.

A picker below the table lets you drill into one OKR. Click "Open detail
view" and the view selector switches.

### OKR detail

Full view of a single OKR:

1. Header — title, description, quarter, status, score, parent OKR link
2. Key Results — each KR with its description, status, score, and a
   metrics row (baseline, current, target, weight)
3. Decision trail — every state-changing event (commits, target changes,
   descopes, abandonments) with the alternatives considered, the chosen
   option, the tradeoff accepted, and supporting evidence

Each decision is rendered as a Streamlit expander; click to see the full
breakdown. This is the *why-it-changed* view that the causal memory layer
makes possible.

### Learnings

Organizational learning themes for the selected team. Filter by category
(execution / planning / alignment / estimation / external / process).
Each theme shows:

- Title and description
- Category badge, quarter, occurrence count
- Affected OKRs (short IDs)
- Supersedes link if this theme replaces an earlier one

This is where you go when prepping for a quarterly review and want to see
"what has the team learned this year".

## Authentication

In dev mode (the default), any UUID works as a bearer token. Just paste a
generated UUID into the sidebar:

```bash
uuidgen   # macOS / many Linux distros
python -c "import uuid; print(uuid.uuid4())"
```

In production, set `CASCADE_API_AUTH_MODE=jwt` on the API and configure a
real JWKS verifier. The console doesn't care — it just sends whatever
token the user pastes.

## Demo data

For a quick demo you can seed a team and OKR via the database:

```bash
docker compose exec postgres psql -U cascade -d cascade -c "
INSERT INTO teams (id, name, slug)
VALUES ('11111111-1111-1111-1111-111111111111', 'Demo Team', 'demo');
"
```

Then paste `11111111-1111-1111-1111-111111111111` as the team ID. The
list will be empty until OKRs are drafted via the MCP server, but the
empty-state copy explains the next step.

## Troubleshooting

**Sidebar shows `:red-badge[unreachable]`.** API isn't running or the URL
is wrong. Try `curl http://localhost:8000/health` to verify.

**`401 Unauthorized` from a route.** Check `api_auth_mode` on the API
server. Dev mode wants UUIDs; JWT mode wants real tokens and fails closed
without a configured verifier.

**`:gray-badge[idle]` in the connection panel.** Bearer token is empty.
Paste one in the sidebar.

**OKRs don't appear after drafting.** The console reads from the REST
API, which reads from Postgres. Drafted OKRs appear after the agent flow
commits — check `query_decisions` from the MCP server, or look for the
commit decision in the decision trail.

## Deployment

In production, the console is a separate container from the API. Both
behind a reverse proxy. Lock down CORS on the API
(`CASCADE_API_CORS_ALLOW_ORIGINS=["https://your-cascade-domain"]`) so
only the console can call it from the browser.

A real deployment would replace the sidebar bearer-token paste with an
OIDC redirect flow — the dependency interface stays the same; only the
sidebar widget swaps.
