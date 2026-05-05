# Memory layer

cascade keeps three kinds of memory because OKR work has three kinds of remembering:

- **Causal memory** — *why* a decision was made. Structured. Queryable with SQL.
- **Conversational memory** — *what* was said in drafting sessions, check-ins, and retros. Vector. Retrieved by similarity.
- **Organizational memory** — *what the company learned*. Hybrid retrieval (BM25 + dense + cross-encoder rerank) over the union of the first two.

## Causal memory — the decisions graph

Every state-changing event on an OKR produces a `decision` row.

```sql
CREATE TABLE decisions (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    okr_id          UUID NOT NULL REFERENCES okrs(id),
    kr_id           UUID REFERENCES key_results(id),
    event_type      TEXT NOT NULL,        -- 'commit', 'target_change', 'close', 'reframe'
    summary         TEXT NOT NULL,        -- one-sentence what changed
    alternatives    JSONB NOT NULL,       -- [{option, reason_rejected}, ...]
    chosen          TEXT NOT NULL,
    tradeoff        TEXT,                 -- explicit tradeoff accepted
    evidence        JSONB,                -- [{source, link, claim}, ...]
    actor_id        UUID NOT NULL REFERENCES users(id),
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    transcript_ref  TEXT                  -- ChromaDB collection + chunk ids
);

CREATE INDEX idx_decisions_okr ON decisions(okr_id, created_at DESC);
CREATE INDEX idx_decisions_event ON decisions(event_type);
```

The `decision_links` table captures *because-of* relationships:

```sql
CREATE TABLE decision_links (
    from_id   UUID NOT NULL REFERENCES decisions(id),
    to_id     UUID NOT NULL REFERENCES decisions(id),
    relation  TEXT NOT NULL,    -- 'caused_by', 'reverses', 'reinforces'
    PRIMARY KEY (from_id, to_id, relation)
);
```

This makes "why is this KR at 0.3?" a graph traversal, not a vector search.

## Conversational memory — ChromaDB

A single collection (`cascade_conversations`) with metadata-rich chunks:

| Metadata field   | Type   | Purpose                                          |
| ---------------- | ------ | ------------------------------------------------ |
| `okr_id`         | UUID   | scope retrieval to a specific OKR                |
| `decision_id`    | UUID?  | link transcript chunk back to a structured row   |
| `agent`          | string | which agent generated this turn                  |
| `quarter`        | string | `2026Q2`, etc. — for time-bounded recall         |
| `team_id`        | UUID   | for cross-team filtering                         |
| `kind`           | string | `drafting`, `checkin`, `retro`, `risk_review`    |

Chunking: 512-token windows with 64-token overlap. Embeddings: `bge-small-en-v1.5`
(384-dim, fast, surprisingly good on enterprise text).

## Organizational memory — hybrid retrieval

For "why" questions and broad organizational queries, we run a three-stage pipeline:

1. **BM25** over decision summaries and transcript chunks — high precision on named
   entities, project codenames, and abbreviations
2. **Dense retrieval** over the same corpus — semantic recall
3. **Cross-encoder rerank** (`ms-marco-MiniLM-L-6-v2`) on the union of top-K from each

This is a deliberate choice. Pure dense retrieval misses queries like "what did we
decide about the EMEA pricing change?" because "EMEA pricing change" is a low-frequency
phrase that BM25 nails. The cross-encoder catches the cases where BM25 keyword-matches
the wrong thing.

## Dynamic context construction

Static context dumps (`CLAUDE.md`-style files) suffer from "lost in the middle" — the
model under-weighs material that isn't at the start or end of its context window. We
build prompts dynamically per agent invocation:

```
ContextBuilder(agent="critic", okr_id=X, conversation_history=...)
  → retrieves: related decisions (3), transcript chunks (5), org snippets (3)
  → assembles: a 600-800 token system prompt tailored to this critique
```

The Drafter sees different context than the Reflector, even for the same OKR. This is the
core inversion: every other tool is racing to inject *more* context. We inject *less*,
but smarter.

## What we deliberately don't store

- Raw LLM outputs that were rejected by HITL — these are noise; we keep the rejection
  reason instead
- PII beyond user IDs — names, emails, phone numbers do not enter the embedding store
- Sensitive payloads (credentials, customer data) — sanitisation runs at ingest

## Retention

Decisions: indefinite. They are the institutional memory.

Transcripts: 18 months by default; configurable per tenant.

Embeddings are recomputed on retention boundary so a transcript expiring tomorrow is no
longer retrievable today.
