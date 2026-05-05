# ADR-0002: Causal memory graph as a structured Postgres relation

- **Status:** Accepted
- **Date:** 2026-05-05
- **Deciders:** @Akash-1512

## Context

The single most-requested capability from teams running OKRs is the ability to ask "*why*
did we set this objective?" months after the fact. Existing OKR tools store *what*
happened (state transitions, comments) but discard *why*: the alternatives that were
considered, the data cited, the dissenting opinions, the tradeoff that was accepted.

A pure conversational-memory approach — embedding everything and retrieving on similarity
— loses the structure. "What were the alternatives" returns whichever paragraph mentions
the word "alternative", not the alternatives themselves.

## Decision

Capture causal events as **structured rows** in a `decisions` table, not as free text in a
vector store. Each row has: the OKR or KR it relates to, the change being made, the
alternatives considered (as a JSONB array of `{option, reason}`), the chosen option, the
tradeoff accepted, the evidence cited, and the actor.

A separate `decision_links` table captures relationships between decisions ("this Q3
target reduction was justified by the Q2 retrospective finding").

The conversational transcripts that produced these decisions live in ChromaDB, linked
back to the structured row via `decision.id`.

When the system answers "why is this KR scored at 0.3?", retrieval is hierarchical:

1. Structured query: pull all `decisions` where `okr_id = X`, ordered by recency
2. Conversational backfill: for each decision, fetch the linked transcript chunks
3. Synthesis: the agent composes a narrative grounded in both

## Consequences

### Positive

- The "why" question has a deterministic answer, not a fuzzy retrieval
- Decisions are queryable with SQL — we can build governance reports without LLM calls
- Cross-decision relationships ("which target reductions cited which retros") are
  expressible as joins
- Structured form is auditable, which matters for any compliance use case

### Negative

- Capture has a friction cost — agents must explicitly write decisions, not just chat
- Schema migrations for the `decisions` table are higher-stakes than vector stores
- The agent prompts for *eliciting* alternatives and tradeoffs are nontrivial

### Neutral

- We carry both Postgres and ChromaDB. The operational complexity is acceptable; both
  were already in scope for other reasons.

## Alternatives considered

- **Vector-only memory** — simple, but loses structure as described above. Rejected.
- **Knowledge graph (Neo4j)** — strictly more expressive but adds operational surface
  area we don't yet need. Reconsider if cross-decision queries dominate workload.
- **JSONB-only on the OKR table** — denormalising decisions into the `okrs` row creates
  hotspot writes and makes cross-OKR queries painful.

## References

- Memory layer design: `docs/architecture/memory.md`
