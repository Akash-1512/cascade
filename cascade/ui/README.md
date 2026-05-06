# cascade.ui

Streamlit operator console — read-only viewer for OKRs, KRs, decision
trails, and organizational learnings. Built on top of the cascade REST API.

## Why read-only

Drafts, commits, target changes, and check-ins flow through the MCP server
because that's where the agent loop lives. Exposing direct mutation
endpoints in the UI would create a path that skips the Critic, the Aligner,
and the Decision recorder. The console shows what the agents have done; new
state happens through MCP clients (Claude Desktop, Cursor, the cascade
CLI).

This is the same architectural choice the REST API made — a single
mutation surface (MCP) keeps governance consistent.

## Files

```
ui/
├── __init__.py
├── app.py             Streamlit entry — sidebar, state, view dispatch
├── api_client.py      httpx wrapper around the REST API
└── views/
    ├── __init__.py
    ├── components.py   Shared widgets: status badges, score indicators,
    │                   category badges, quarter selector
    ├── okr_list.py     Sortable table of OKRs with drill-down
    ├── okr_detail.py   Single OKR — KRs, score, decision trail
    └── learnings.py    Quarterly learning themes panel
```

## Running

```bash
# Bring up the cascade stack first
docker compose up -d
alembic upgrade head
uvicorn cascade.api.main:app --host 0.0.0.0 --port 8000 &

# Run the console
streamlit run cascade/ui/app.py
```

Then open the printed URL (default `http://localhost:8501`). The sidebar
prompts for:

- **API URL** — defaults to `http://localhost:8000`. Override with
  `CASCADE_UI_API_URL`.
- **Bearer token** — any UUID in dev mode; a real JWT in production.
  Override with `CASCADE_UI_BEARER_TOKEN`.
- **Team ID** — UUID of the team whose OKRs you're viewing.
- **Quarter** — current quarter is preselected; "All" shows everything.
- **View** — OKR list / OKR detail / Learnings.

The connection-status panel in the sidebar runs `/health` on every render
so a broken API surface shows up immediately rather than as opaque view
errors.

## API client

`cascade.ui.api_client.APIClient` is a thin synchronous wrapper around
`httpx.Client`. Single-typed `APIError` for all failures (network, 4xx,
5xx) so views handle one exception type. Tests use `httpx.MockTransport` to
stub responses without standing up a real server.

```python
from cascade.ui.api_client import APIClient
client = APIClient.from_env(bearer_token=str(my_uuid))
body = client.list_team_okrs(team_id, quarter="2026Q2")
```

## Components

`cascade.ui.views.components` is the shared visual vocabulary:

- `status_badge(status)` — coloured pill with semantic colour mapping
  (green = on track, orange = at risk, red = off track, etc.)
- `score_indicator(score)` — coloured percentage with thresholds matching
  the Risk Sentinel (< 30% red, 30–70% blue, ≥ 70% green)
- `category_badge(category)` — coloured pill for learning categories
- `format_iso_datetime(value)` — short readable form, forgiving of Z
  suffixes and parse failures
- `current_and_recent_quarters(count=N)` — populates the quarter
  dropdown without manual maintenance

Unknown statuses fall back to a grey badge rather than raising. This is
deliberate forward-compatibility: the API may add a new status before the
UI ships matching colours.

## Testing

Three layers of coverage:

- **`tests/unit/test_ui_components.py`** — pure-function tests of the
  shared visual helpers
- **`tests/unit/test_ui_api_client.py`** — `httpx.MockTransport`-driven
  client tests (auth header presence, query params, error mapping, network
  failure wrapping)
- **`tests/unit/test_ui_app.py`** — Streamlit `AppTest`-driven smoke tests
  with the API client patched; exercises sidebar prompts, view dispatch,
  empty states, and error paths

`AppTest` is slow per-test (each starts a fresh script run) so we keep
those focused on flows the lower layers can't cover.

## Deployment notes

The console is a thin client over the API; it ships separately:

- One container running the Streamlit app
- One container running `uvicorn cascade.api.main:app`
- A reverse proxy in front of both

`CASCADE_UI_API_URL` should point at the API service from inside the cluster.
`CASCADE_UI_BEARER_TOKEN` defaults to empty so the user logs in through the
sidebar; in a real deployment that would be replaced by a real OIDC flow.

## See also

- [REST API runbook](../../docs/runbooks/rest-api.md)
- [MCP server runbook](../../docs/runbooks/mcp-server.md) — the mutation surface
- [Operator console runbook](../../docs/runbooks/operator-console.md)
