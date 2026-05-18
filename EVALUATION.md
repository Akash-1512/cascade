# Evaluating cascade

A walkthrough for technical reviewers — hiring managers, staff engineers,
anyone trying to decide whether the person who built this knows what
they're doing. Three reading depths; pick the one that fits your time.

> No API keys required for any of this. The eval gate, full test suite,
> demo seed, and operator console all work with the included fakes.

---

## 5-minute path — does it actually work?

```bash
git clone https://github.com/Akash-1512/cascade.git
cd cascade
make evaluate
```

That single command does the full reviewer check: installs dependencies,
runs lint, runs all 443 tests (unit + integration), runs the eval gate
with fakes, runs the Helm chart structural validator, and prints a
summary. Takes ~2 minutes on a modern laptop.

While that runs, read [`ARCHITECTURE.md`](ARCHITECTURE.md) — six mermaid
diagrams covering the system, agent topology, HITL sequence, data model,
eval gate flow, and deployment shape. Organised for progressive
disclosure; the first three diagrams alone tell you what cascade does
and how the agents disagree.

**What this verifies in 5 minutes:**
- The codebase builds clean — lint, format, types declared
- 443 tests pass with no API keys, no Docker, no Postgres (SQLite override)
- The eval gate runs end-to-end against fake models
- The Helm chart is structurally valid
- The architecture is documented at a level a senior engineer can audit

**If `make evaluate` fails**, that's the bug report. Open an issue with
the output; nothing in this repo should require manual setup beyond
Python 3.12 and `make`.

---

## 30-minute path — what's it like to use?

After `make evaluate`, seed the database and look at the actual product:

```bash
make demo                           # alembic upgrade + seed_demo

# Terminal 1: REST API
.venv/bin/uvicorn cascade.api.main:app --port 8000

# Terminal 2: operator console
.venv/bin/streamlit run cascade/ui/app.py
```

Streamlit opens at http://localhost:8501. Paste the team UUID printed
by `make demo` into the sidebar; use any UUID as the bearer token (the
API runs in dev mode by default). You'll see:

- Two seeded OKRs with KRs at varying confidence levels
- A full decision trail for each, including target changes and reframes
- An organizational learning row distilled from the trail

Try the REST API directly:

```bash
TEAM=<uuid from make demo>
TOKEN=$(uuidgen)

curl -H "Authorization: Bearer $TOKEN" \
  "http://localhost:8000/v1/teams/$TEAM/okrs?quarter=2026Q1" | jq

# Pick an OKR id and trace the decision history:
curl -H "Authorization: Bearer $TOKEN" \
  "http://localhost:8000/v1/okrs/<OKR_ID>/decisions?limit=20" | jq
```

The decision trail shows alternatives considered, the chosen path, and
the tradeoff accepted — every change is structured, not free-text.

Read these in order while the demo's running:
1. [`cascade/api/README.md`](cascade/api/README.md) — REST surface and
   the read/mutate split rationale
2. [`docs/architecture/agents.md`](docs/architecture/agents.md) — the
   six agents and how they disagree
3. [`CHANGELOG.md`](CHANGELOG.md) — what shipped when, with design
   rationale per release

**What this verifies in 30 minutes:**
- The product is real — you can query, browse, see structured data
- The decision-trail design isn't theoretical; it's populated and
  queryable
- The REST API is consistent, documented, and ergonomic
- The release cadence is real — 18 tagged releases with detailed notes

---

## 2-hour path — would I hire this person?

For when you want to evaluate engineering judgment, not just "did they
finish the thing." Take this in any order:

### Read the load-bearing code
Three files that carry the most weight:

- [`cascade/orchestrator/graph.py`](cascade/orchestrator/graph.py) —
  the LangGraph state graph, supervisor decision function, HITL
  interrupt handling. Look for the "awaiting_human is the terminal
  signal" pattern that makes pause-and-resume actually correct.
- [`cascade/mcp/tools.py`](cascade/mcp/tools.py) — the 10 MCP tools.
  `start_okr_draft` and `resume_okr_draft` are where the HITL flow
  meets the protocol.
- [`cascade/api/jwt_verifier.py`](cascade/api/jwt_verifier.py) — JWKS
  client with TTL cache, provider-agnostic JWT verification, three
  distinct failure shapes mapped to 503/401.

### Read the load-bearing tests
- [`tests/integration/test_orchestrator_hitl.py`](tests/integration/test_orchestrator_hitl.py)
  — exercises the full pause-resume cycle including the v0.13.0 fix
  for the abandon termination bug
- [`tests/unit/test_jwt_verifier.py`](tests/unit/test_jwt_verifier.py)
  — verifies the three failure shapes individually
- [`tests/unit/test_observability_handlers.py`](tests/unit/test_observability_handlers.py)
  — sys.modules injection to test branching without optional deps

### Read the design decisions
- [`docs/adr/`](docs/adr/) — three ADRs (LangGraph orchestration,
  causal memory graph, dynamic context construction)
- [`TYPING.md`](TYPING.md) — why mypy is advisory now and the named
  threshold for flipping it to blocking
- [`CHANGELOG.md`](CHANGELOG.md) — every release names the
  load-bearing contract or trade-off it introduced

### Try the agent loop end-to-end
If you have a Groq API key (free tier at console.groq.com):

```bash
export GROQ_API_KEY=gsk_...

# Connect Claude Desktop to the MCP server (stdio):
# Add to ~/Library/Application Support/Claude/claude_desktop_config.json:
#
#   {
#     "mcpServers": {
#       "cascade": {
#         "command": "python",
#         "args": ["-m", "cascade.mcp.server"],
#         "cwd": "/absolute/path/to/cascade",
#         "env": { "GROQ_API_KEY": "gsk_..." }
#       }
#     }
#   }

# Then in Claude Desktop, ask it to draft an OKR. Try one that conflicts
# with an existing OKR's resources — watch the Aligner pause for human
# input and the resume flow play out.
```

### Try the Helm chart against a real cluster
```bash
# Requires: kind / minikube / k3d + helm 3.16+
helm dependency update helm/cascade/
helm install cascade helm/cascade/ \
  --namespace cascade --create-namespace \
  --values helm/cascade/values-dev.yaml \
  --set secrets.groqApiKey="$GROQ_API_KEY"
```

The chart's `NOTES.txt` walks you through migrations, demo seed, and
port-forward verification.

**What this verifies in 2 hours:**
- The architecture decisions hold up to scrutiny — every load-bearing
  trade-off is named and justified
- The test design is intentional, not coverage-chasing
- The release notes carry actual engineering judgment, not feature
  bullets
- The deployment story is real — you can run it in a real cluster

---

## What to look for

Things a senior reviewer would notice that signal "this person is good
at the job":

1. **Decision rules pinned in tables, not prose.** See the supervisor
   decision table and resumption decision table in ARCHITECTURE.md.
   Load-bearing contracts get a place where they can't be
   accidentally regressed.

2. **Fail-quiet observability.** The observability module catches
   construction failures, missing optional packages, and mid-run
   rejections. A LangSmith outage doesn't crash the agent loop. See
   `cascade/observability/handlers.py`.

3. **Read/mutate split as usage-pattern, not layer boundary.** Both
   REST POSTs and MCP tools call the same domain repositories. The
   split is "REST when the caller knows the answer, MCP when the
   agent does." Documented explicitly in `cascade/api/README.md`.

4. **Advisory CI for mypy with a named threshold.** Strict-by-config,
   advisory-by-CI until error count drops under 10. Makes the work
   finite and trackable. See `TYPING.md`.

5. **Body-override-defaults-to-principal pattern.** REST POSTs let
   service accounts record events on behalf of real users without
   sharing JWTs. Audit trail correctness for CI pipelines and
   automation. See `cascade/api/routes/decisions.py`.

6. **Two-layer Helm validation.** Python structural validator inside
   pytest for fast feedback + real `helm lint` in CI for
   authoritative checks. Different tools, complementary coverage.

7. **Atomic conventional commits with full rationale.** Browse the
   commit log on `main` — each commit message names what changed,
   why, and what the trade-off was. Not "fix bug" or "update tests."

If any of those patterns are unfamiliar, the inline code comments
explain them. If they're familiar, you're looking at the kind of
engineering attention production agentic AI needs.

---

## Contact

Akash Chaudhari — [LinkedIn](https://www.linkedin.com/in/akash-chaudhari-1512/)
· ag.chaudhari.1512@gmail.com
