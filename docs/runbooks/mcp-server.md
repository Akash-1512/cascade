# MCP server

cascade exposes its capabilities over the [Model Context Protocol][mcp-spec] so
the same operations are available from Claude Desktop, Cursor, or any
MCP-compatible client. Eight tools are registered:

| Tool | Purpose |
|---|---|
| `list_okrs` | Compact list view of OKRs filtered by team and quarter |
| `get_okr` | Full Objective view with KRs and derived scores |
| `draft_okr` | Drafter + Critic loop returning a proposal and verdict |
| `score_okr` | Current score breakdown for an existing Objective |
| `log_checkin` | Coach-mediated check-in with structured persistence |
| `query_decisions` | Causal trail for an Objective |
| `assess_risk` | Risk Sentinel agent with intervention recommendations |
| `get_alignment` | Aligner agent with vertical and horizontal checks |

[mcp-spec]: https://modelcontextprotocol.io/

## Running locally

```bash
# Stdio transport (used by Claude Desktop and Cursor)
python -m cascade.mcp.server

# SSE on the configured port for cross-process clients
python -m cascade.mcp.server --transport sse

# Streaming HTTP — preferred for production
python -m cascade.mcp.server --transport streamable-http
```

The server reads configuration from environment variables (or `.env` — see
[`.env.example`](../../.env.example)). Required for any non-trivial use:

- `DATABASE_URL` — Postgres connection string
- `GROQ_API_KEY` — primary LLM provider
- `MCP_PORT` — only when using SSE or streamable-http (default 8765)

## Claude Desktop configuration

Add cascade to `claude_desktop_config.json`:

```json
{
  "mcpServers": {
    "cascade": {
      "command": "python",
      "args": ["-m", "cascade.mcp.server"],
      "env": {
        "DATABASE_URL": "postgresql+psycopg://cascade:cascade@localhost:5432/cascade",
        "GROQ_API_KEY": "your-key-here"
      }
    }
  }
}
```

Restart Claude Desktop after editing. The cascade tools appear in the tool
picker and can be called directly: "use cascade to draft an OKR for reaching
PMF in the SMB segment", "show me the decision history for this OKR".

## Cursor configuration

Cursor reads from `~/.cursor/mcp.json`:

```json
{
  "mcpServers": {
    "cascade": {
      "command": "python",
      "args": ["-m", "cascade.mcp.server"],
      "env": {
        "DATABASE_URL": "postgresql+psycopg://cascade:cascade@localhost:5432/cascade",
        "GROQ_API_KEY": "your-key-here"
      }
    }
  }
}
```

## Tool examples

### Drafting a new Objective

```
draft_okr(intent="We want to win in the SMB segment this quarter — improve trial
conversion and lift product engagement so we have a strong base going into Q3.")
```

Returns a `DraftResult` with a proposed Objective + KRs, the Critic's verdict,
overall score, and any suggestions. The proposal is **not yet persisted** — the
Critic might reject or request revision.

### Asking why an OKR was set the way it was

```
query_decisions(objective_id="2f3e1c4a-...")
```

Returns the full causal trail — every commit, target change, and reframe with
the alternatives considered, the chosen option, and the tradeoff accepted. This
is what makes cascade more than yet-another-OKR-tool: the *why* survives.

### Logging a check-in

```
log_checkin(
  objective_id="2f3e1c4a-...",
  key_result_id="9b7d8a2e-...",
  progress_value=320,
  confidence="medium",
  narrative="Hit 320 this week. Small dip in conversion but engagement is up.",
  author_id="..."
)
```

Returns a `CheckInResult` with the persisted check-in id, the new status, and a
coaching message. If the user mentioned a target change in the narrative, the
Coach captures it as a decision — but persistence requires explicit human
confirmation in a follow-up call.

## Human-in-the-loop drafting

`start_okr_draft` and `resume_okr_draft` together support pause-and-resume
drafting. When the orchestrator graph pauses on an alignment conflict or the
Critic loops past the iteration cap, the tool returns a paused state with a
`thread_id`. The client passes that `thread_id` back to `resume_okr_draft`
with a decision once a human has weighed in.

```text
start_okr_draft(intent="...")
        │
        ▼
LangGraph runs Drafter → Critic → Aligner
        │
        ├── Aligned → returns {status: "completed", proposal, verdict}
        │
        └── Blocked / iteration cap → returns {status: "paused",
                                                thread_id: "...",
                                                reason: "alignment_conflict",
                                                conflicts: [...]}

resume_okr_draft(thread_id, decision, notes)
        │
        ├── decision="commit" → force aligned, demote blocking conflicts
        │                         to info, complete
        │
        ├── decision="revise" → clear proposal, rerun Drafter (may pause
        │                         again on the next pass)
        │
        └── decision="abandon" → mark blocked with audit conflict carrying
                                   the abandonment notes, complete
```

State lives in the LangGraph checkpointer, an `AsyncSqliteSaver` opened at
server startup. By default the checkpointer is in-memory — paused drafts
don't survive a server restart. Set `CASCADE_MCP_CHECKPOINTER_PATH` to a
file path for durable pauses:

```bash
export CASCADE_MCP_CHECKPOINTER_PATH=/var/lib/cascade/checkpoint.db
```

The directory must exist and be writable by the MCP server process.

### Example flow from Claude Desktop

```
User: Draft an OKR for the Q2 SMB conversion focus.

[Claude calls start_okr_draft with intent="Q2 SMB conversion focus"]
[Returns: status="paused", reason="alignment_conflict",
          thread_id="...",
          conflicts=[{description: "Both OKRs need the same engineering capacity",
                      severity: "blocking"}]]

Claude: I drafted the OKR but the Aligner flagged a blocking conflict —
the proposed KR competes with the v2 retention engine work for the same
backend capacity. You can:
  1. Commit anyway (we accept the resource contention)
  2. Revise the draft (I'll try a different KR shape)
  3. Abandon

User: Let's revise — change the third KR to be qualitative instead.

[Claude calls resume_okr_draft(thread_id, "revise",
                               notes="Make KR3 qualitative")]
[Returns: status="completed", proposal=<new draft>, verdict="aligned"]

Claude: Here's the revised draft, now aligned:
...
```



- **stdio** — single-client, launched by Claude Desktop / Cursor. The simplest
  path. Lowest latency. No network exposure.
- **SSE** — multi-client, server stays up across sessions. Good for shared
  developer environments.
- **streamable-http** — production deployments behind a reverse proxy. JWT auth
  and rate limiting belong here, not in the MCP server itself.

## Troubleshooting

**Tools don't appear in Claude Desktop.** Check the logs at
`~/Library/Logs/Claude/mcp.log`. Most often this is a missing dependency in the
Python environment Claude Desktop launched the server in — pin
`PYTHONPATH` or activate a virtualenv before launch.

**`structured_output failed` warnings.** Expected when the configured LLM
doesn't fully support OpenAI-style function calling. The agents fall back to
raw JSON parsing — you'll see one warning per agent invocation but tools still
work correctly.

**Sessions hang on commit.** Check that `DATABASE_URL` points at a running
Postgres. The MCP server doesn't bring up its own DB — see
[`docker-compose.yml`](../../docker-compose.yml) for a local stack.
