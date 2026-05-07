# cascade.mcp

The Model Context Protocol surface — ten tools that MCP clients (Claude
Desktop, Cursor, any MCP-compatible agent) use to draft, score, align, and
check in on OKRs.

## The ten tools

### Read-side

| Tool | Inputs | Returns | Backed by |
|---|---|---|---|
| `list_okrs` | `team_id`, `quarter?` | `list[ObjectiveSummary]` | `ObjectiveRepository.list_for_team` |
| `get_okr` | `objective_id` | `ObjectiveView` | `ObjectiveRepository.get` |
| `score_okr` | `objective_id` | `ScoreResult` (per-KR breakdown) | Domain `score` properties |
| `query_decisions` | `objective_id`, `limit?` | `list[DecisionView]` | `DecisionRepository.list_for_objective` |
| `assess_risk` | `objective_id`, `weeks_elapsed?` | `RiskAssessmentView` | `assess_risk` agent |
| `get_alignment` | `objective_id` | `AlignmentResultView` | `check_alignment` agent |

### Mutating / agent-driving

| Tool | Inputs | Returns | Backed by |
|---|---|---|---|
| `draft_okr` | `intent` | `DraftResult` (proposal + verdict) | `draft_objective` + `critique_proposal` |
| `log_checkin` | KR + progress + narrative | `CheckInResult` | `run_checkin` + `CheckInORM.save` |
| `start_okr_draft` | `intent` | `StartOkrDraftResult` (paused or completed) | LangGraph + checkpointer |
| `resume_okr_draft` | `thread_id`, `decision`, `notes?` | `ResumeOkrDraftResult` | `resume()` helper |

## HITL drafting flow

`start_okr_draft` and `resume_okr_draft` together expose the pause-and-resume
flow that the orchestrator graph supports via LangGraph's `interrupt()`
primitive. The pattern from a Claude Desktop conversation:

1. User asks Claude to draft an OKR. Claude calls `start_okr_draft(intent="...")`.
2. The graph runs Drafter → Critic → Aligner. If everything aligns, the tool
   returns `state.status == "completed"` and Claude shows the user the
   proposal.
3. If the Aligner blocks (a resource conflict with a peer OKR, vertical
   drift from the parent, etc.) or the Critic loops past the iteration cap,
   the graph pauses. The tool returns `state.status == "paused"` with the
   reason, the proposal so far, and any blocking conflicts. Claude shows
   the user what's blocking and asks how to proceed.
4. The user decides: commit the proposal anyway, ask for a revision, or
   abandon. Claude calls `resume_okr_draft(thread_id, decision, notes)`.
5. The graph resumes from the paused state. On `commit`, it forces alignment
   to "aligned" and demotes blocking conflicts to info, then completes. On
   `revise`, it clears the proposal and runs the Drafter again — this can
   pause again, in which case the tool returns another `paused` state with
   the same `thread_id`. On `abandon`, it terminates with an audit-trail
   alignment showing the abandonment reason.

The `thread_id` is opaque — the client just passes it back. The state lives
in the LangGraph checkpointer (`AsyncSqliteSaver`) for the duration of the
MCP server process. Set `CASCADE_MCP_CHECKPOINTER_PATH` to a file path to
preserve paused drafts across server restarts; the default `:memory:` keeps
them only for the current process.

## Files

```
mcp/
├── __init__.py     Public API
├── schemas.py      Wire-format Pydantic types — distinct from cascade.domain
├── adapters.py     Conversion between domain types and wire types
├── tools.py        Tool registration + AgentContext (carries deps)
└── server.py       Entry point with argparse for transport selection
```

## Wire schemas separate from domain

`cascade.mcp.schemas` is intentionally distinct from `cascade.domain`:

| Domain | Wire |
|---|---|
| `UUID` | `str` |
| `datetime` | ISO 8601 `datetime` (FastMCP serialises to string) |
| `Quarter(year, quarter)` | `"2026Q2"` |
| Nested `Alternative` Pydantic models | `dict[str, str]` |
| `MetricType` enum | `Literal["number", "percentage", ...]` |

This means the protocol can evolve without touching the database schema.
Adapters in `cascade.mcp.adapters` handle conversion both ways.

## AgentContext

```python
@dataclass(frozen=True, slots=True)
class AgentContext:
    sessionmaker: async_sessionmaker[AsyncSession]
    model: BaseChatModel

    @asynccontextmanager
    async def session(self) -> AsyncIterator[AsyncSession]:
        async with self.sessionmaker() as s:
            try:
                yield s
                await s.commit()
            except Exception:
                await s.rollback()
                raise
```

Single object holds dependencies. The `session()` context manager scopes
transactions to a single tool call with auto-rollback on exception. No
transaction leaks across calls.

## Three transports

| Transport | Use case | Latency | Network exposure |
|---|---|---|---|
| `stdio` | Claude Desktop / Cursor | Lowest | None |
| `sse` | Multi-client cross-process | Medium | Local |
| `streamable-http` | Production (behind proxy) | Medium | Cross-network |

Stdio is the default. JWT auth and rate limiting belong in the proxy in front
of `streamable-http`, not in this module.

## Why logs go to stderr

MCP stdio transport speaks JSON-RPC over stdout. Anything written to stdout
that isn't a JSON-RPC message corrupts the stream and the client silently
drops the connection.

```python
logging.basicConfig(
    level=settings.log_level,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    stream=sys.stderr,  # critical — keep stdout clean
)
```

This is the most common cause of "tools don't appear in Claude Desktop" — the
runbook documents it explicitly because everyone hits it once.

## Testing

- `tests/unit/test_mcp_adapters.py` — 10 tests on adapter conversions
- `tests/unit/test_mcp_server.py` — 3 tests on the argparse entry point
- `tests/integration/test_mcp_tools.py` — 9 integration tests building a real
  FastMCP server with the registered tools and exercising each through
  `mcp.call_tool` against SQLite + `FakeChatModel`

## Configuration

The server reads from `cascade.config.Settings` (pydantic-settings backed by
environment variables). Key inputs:

```bash
DATABASE_URL=postgresql+psycopg://cascade:cascade@localhost:5432/cascade
GROQ_API_KEY=...
MCP_HOST=0.0.0.0           # SSE / streamable-http only
MCP_PORT=8765              # SSE / streamable-http only
LOG_LEVEL=INFO
```

Full `.env.example` at the repo root.

## See also

- [MCP server runbook](../../docs/runbooks/mcp-server.md)
- [Architecture overview](../../docs/architecture/overview.md)
