# ADR-0003: Dynamic context construction over static context files

- **Status:** Accepted
- **Date:** 2026-05-05
- **Deciders:** @Akash-1512

## Context

Many AI coding and analysis tools rely on static context files (`CLAUDE.md`,
`AGENTS.md`, `.cursorrules`) injected wholesale into the model's context window.
This pattern has two well-documented failure modes:

1. **"Lost in the middle"** — when a 5,000-token static block is at the start of
   the prompt, the model under-weights material between the start and end. The
   middle is effectively unread. Recent evaluation work (notably the ETH Zurich
   2026 study on context utilisation) has shown this is significant enough that
   *adding* context can degrade output quality, not improve it.

2. **One-size-fits-all** — the same context is shown to every task. The Drafter
   needs different context than the Reflector, even on the same OKR. Static
   files cannot tailor.

cascade's agents need contextual grounding (especially the Drafter when revising
an existing OKR — it should see the past decisions), but copying the static-file
pattern would inherit both failure modes.

## Decision

Replace static context with **per-call retrieval-augmented prompt construction**,
implemented in :class:`cascade.memory.context_builder.ContextBuilder`.

For each agent invocation:

1. The agent is identified by name (`drafter`, `critic`, etc.) so a per-agent
   retrieval budget can be applied.
2. Causal memory (decisions on the OKR) is fetched from the relational store.
3. Conversational memory is retrieved through the hybrid pipeline (BM25 + dense
   + cross-encoder rerank) with the agent's task as the query.
4. The result is assembled into a small (target: 600–800 token) context block
   tailored to that specific call.

The Drafter on a fresh OKR sees no decisions and a small set of team-scoped
chunks. The Drafter revising the same OKR three weeks later sees the decision
trail with tradeoffs accepted, plus the previous drafting transcripts. The
Reflector at quarter-end sees aggregated retrospective patterns instead.

## Consequences

### Positive

- Each agent sees only what is relevant — no "lost in the middle"
- Token budgets are per-call, not per-session, so cost is bounded
- The retrieval pipeline can be improved without changing agent code
- Causal memory reaches the model — the "we already considered and rejected
  alternative X" loop is closed

### Negative

- Each agent invocation does a retrieval pass — adds 50–200 ms latency at the
  in-process scale we run at; a few hundred ms at production scale with reranker.
- The retrieval pipeline becomes a critical path: a bug here degrades every
  agent. Eval-gate coverage in CI mitigates this.
- Per-agent retrieval budgets are tunable and have to be tuned. We start with
  conservative defaults (3–5 chunks) and revisit during eval-driven tuning.

### Neutral

- The pattern requires a memory layer that supports filtering (by OKR, team,
  quarter, kind). This is a hard requirement on the store implementation; both
  the in-memory fake and ChromaDB satisfy it.

## Alternatives considered

- **Static context file injection** — rejected for the reasons above.
- **Long-context models without retrieval** — defers the problem to the model
  rather than solving it. The "lost in the middle" finding holds at 200K+
  context windows.
- **Single retrieval pass at the start of a session** — does not scale across
  agents that need different views of the same memory.

## References

- Memory layer architecture: `docs/architecture/memory.md`
- ContextBuilder implementation: `cascade/memory/context_builder.py`
- ADR-0002 (causal memory graph)
