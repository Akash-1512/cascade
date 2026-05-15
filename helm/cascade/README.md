# cascade Helm chart

Deploy cascade — REST API, MCP server, operator console — to a Kubernetes
cluster.

## What you get

Three Deployments (API, MCP, UI) behind ClusterIP Services. Postgres
ships as an optional subchart dependency for baseline installs; production
deployments point at managed Postgres instead. The MCP server's LangGraph
checkpointer gets a PersistentVolumeClaim so paused HITL drafts survive
pod restarts.

## Quick install (local cluster)

```bash
helm dependency update helm/cascade/
helm install cascade helm/cascade/ \
  --namespace cascade --create-namespace \
  --values helm/cascade/values-dev.yaml \
  --set secrets.groqApiKey="$GROQ_API_KEY"
```

Then port-forward and run migrations:

```bash
kubectl --namespace cascade port-forward svc/cascade-api 8000:8000
# in another terminal:
kubectl --namespace cascade exec deploy/cascade-api -- alembic upgrade head
kubectl --namespace cascade exec deploy/cascade-api -- python -m cascade.scripts.seed_demo --verbose
```

See `templates/NOTES.txt` (printed after install) for the full post-install
checklist tailored to your values.

## Production deployments

Override these from the defaults:

| Setting | Why |
|---|---|
| `image.tag` | Pin to a specific cascade version, not `appVersion` |
| `api.authMode: jwt` | Switch from dev auth to JWT verification |
| `secrets.jwt.*` | Wire JWKS URL, issuer, audience for your IdP |
| `secrets.existingSecret` | Use externally-managed Secret (sealed-secrets, ESO, Vault) |
| `postgresql.enabled: false` | Use managed Postgres (RDS, Cloud SQL) |
| `externalDatabase.*` | Wire the managed Postgres connection |
| `config.corsAllowOrigins` | Tighten from `*` to your console's origin |
| `api.replicaCount` | Scale to your RPS target |

## Configuration surface

All keys are documented inline in `values.yaml`. The doc-as-config approach
keeps the canonical reference next to the defaults — no chart-README drift.

### Image source

Default image: `ghcr.io/akash-1512/cascade:{appVersion}`. The image isn't
auto-built by the cascade CI yet; the chart assumes the image exists.
Override `image.repository` to point at your own registry while the
publish pipeline is being built.

### Secret management

Two modes:

- **Inline** (`secrets.existingSecret: ""`): the chart creates a Secret
  with the keys you provide via `--set` or `--values`. Convenient for
  dev; problematic for production because the values land in your release
  history.
- **External** (`secrets.existingSecret: cascade-prod-secrets`): the
  chart references a Secret you create out-of-band. Recommended for any
  shared cluster.

Required keys regardless of mode (when JWT auth is enabled, the JWKS URL
goes in the ConfigMap; the JWT secrets are not secret per se, but live in
the Secret by convention so a single env-from spec covers both):

| Key | When required |
|---|---|
| `GROQ_API_KEY` | always |
| `TOGETHER_API_KEY` | optional fallback |
| `LANGSMITH_API_KEY` | if observability.langsmith.tracing |
| `LANGFUSE_PUBLIC_KEY` + `LANGFUSE_SECRET_KEY` | if using Langfuse |

### Postgres

The bitnami subchart's defaults are sized for small self-hosted clusters
(~1Gi storage, 256Mi memory). Production deployments almost always want a
managed Postgres — set `postgresql.enabled: false` and configure
`externalDatabase.*`.

### MCP server replicas

`mcp.replicaCount` stays at 1 by default. The LangGraph checkpointer
holds state on a ReadWriteOnce PVC, so scaling horizontally would deadlock
on the volume mount. Workarounds:

1. Switch to a shared-state checkpointer backend (Postgres) — not yet
   implemented in cascade; tracked as a future enhancement.
2. Set `mcp.checkpointer.persistence.enabled: false` and accept that
   paused HITL drafts don't survive pod restarts. Then `replicaCount`
   can go higher safely.

## Testing the chart

```bash
helm lint helm/cascade/
helm template helm/cascade/ --values helm/cascade/values-dev.yaml | kubectl apply --dry-run=client -f -
```

CI runs both on every PR via `.github/workflows/ci.yml::helm-lint`.

## Versioning

Chart version (`Chart.yaml::version`) and app version (`appVersion`) are
tracked separately:

- `appVersion` matches `cascade.__version__` exactly
- `version` (chart) follows the app's minor track: chart-0.X.y for
  app-0.X.z. A chart-only fix (template bug, default tweak) bumps the
  chart patch without bumping appVersion.

Current: chart `0.1.0`, app `0.18.0`.
