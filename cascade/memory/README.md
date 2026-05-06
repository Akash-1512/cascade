# cascade.memory

Three storage tiers behind clean Protocol interfaces, plus dynamic
task-aware prompt assembly.

## The three tiers

| Tier | Purpose | Implementation | Owned by |
|---|---|---|---|
| **Causal memory** | Structured Decision rows with alternatives, tradeoffs, evidence | Postgres + JSONB | `cascade.storage.repositories.decision` |
| **Conversational memory** | Vector-indexed transcript chunks | ChromaDB (default ONNX MiniLM) | `ChromaMemoryStore` |
| **Hybrid retrieval** | BM25 + dense + cross-encoder rerank | `HybridRetriever` | This module |

The agents do not access the storage layers directly. They go through the
`Retriever` and `MemoryStore` Protocols, which lets us swap fakes in for tests
and production implementations in for deployment without touching agent code.

## Files

```
memory/
├── __init__.py          Public API; lazy-imports ChromaMemoryStore via __getattr__
├── types.py             Protocols (Embedder, Reranker, Retriever, MemoryStore)
│                        + value types (MemoryChunk, RetrievedChunk, MemoryQuery)
├── fakes.py             HashEmbedder, IdentityReranker, InMemoryStore,
│                        StaticRetriever — deterministic test fakes
├── bm25.py              BM25Index — keyword index for rare terms and codenames
├── retrieval.py         HybridRetriever — BM25 + dense + rerank pipeline
├── reranker.py          LLMReranker — cross-encoder pattern via chat model
├── store.py             ChromaMemoryStore — production vector store
├── context_builder.py   ContextBuilder — dynamic per-agent prompt assembly
└── recorder.py          MemoryRecorder — bridges agent runs to all three tiers
```

## Hybrid retrieval, in pictures

```
                user query
                    │
                    ▼
        ┌───────────────────────┐
        │  ChromaMemoryStore    │  Dense top-K (K=20)
        │  search_dense()       │  Catches: paraphrases, semantic similarity
        └───────────┬───────────┘
                    │
                    ▼
        ┌───────────────────────┐
        │  BM25Index            │  Keyword top-K (K=20)
        │  search()             │  Catches: rare terms, codenames, named entities
        └───────────┬───────────┘
                    │
                    ▼ (de-duplicated by chunk id)
        ┌───────────────────────┐
        │  LLMReranker          │  Cross-encoder scoring
        │  rerank()             │  Resolves disagreement; falls back to neutral
        └───────────┬───────────┘  scores if scoring fails
                    │
                    ▼
              top N results
              (limit per query)
```

Why each stage matters:

- **BM25** catches phrases like "EMEA pricing change", "ContextPool migration",
  "Q2 SMB cohort" — rare terms where dense embeddings dilute the signal.
- **Dense** catches paraphrases — "trial conversion" → "signup-to-paid funnel".
- **Cross-encoder rerank** resolves disagreements joint-scored — when BM25
  ranks a chunk highly but dense disagrees, the cross-encoder makes the call.

A single retriever loses two of these groups. ADR-0003 documents the choice.

## ContextBuilder: per-agent budgets

The conventional pattern of dumping a static `CLAUDE.md` into every prompt has
two failure modes: "lost in the middle" under-weighting, and one-size-fits-all
context blocks.

`ContextBuilder` runs retrieval per agent invocation with a per-agent budget:

| Agent | Chunks |
|---|---|
| Drafter | 3 |
| Critic | 2 |
| Aligner | 5 |
| Check-in Coach | 4 |
| Reflector | 8 |
| Risk Sentinel | 4 |

Causal memory (decisions on the OKR) is fetched separately from the relational
store and rendered into a "Decision history" section. Conversational memory
goes into a "Related context from memory" section.

```python
builder = ContextBuilder(retriever=retriever, decision_repository=decision_repo)
ctx = await builder.build(
    agent="drafter",
    intent="Revise the SMB target after pipeline review",
    okr_id=okr.id,
    team_id=team.id,
    quarter="2026Q2",
)
# ctx.rendered → small, tailored context block
# ctx.decisions / ctx.chunks → structured pieces for traces
```

## MemoryRecorder: the commit path

When the agent graph commits a drafted Objective, three artefacts must be
persisted in the right order:

```
1. ObjectiveRepository.create(...)         # we need the id first
        │
        ▼
2. DecisionRepository.create(              # references objective_id
       event_type=OBJECTIVE_COMMIT,
       alternatives=[earlier drafts],
       chosen=final draft,
       tradeoff=last revision suggestions,
       evidence=[critique scores],
   )
        │
        ▼
3. MemoryStore.add(                         # references both ids in metadata
       chunks=[transcript per iteration],
   )
```

If anything fails mid-flight, the SQL transaction rolls back the first two and
the chunks are simply not added. The recorder is the only place agent runs
become durable state.

## Lazy imports

`cascade.memory.__init__` uses `__getattr__` to defer the ChromaDB import:

```python
def __getattr__(name: str) -> object:
    if name == "ChromaMemoryStore":
        from cascade.memory.store import ChromaMemoryStore
        return ChromaMemoryStore
    raise AttributeError(...)
```

Importing `cascade.memory` in test code does not pull in `chromadb`. Test runs
that don't need it stay fast.

## Testing

- `tests/unit/test_memory_primitives.py` — 19 tests on the fakes and BM25
- `tests/unit/test_context_builder.py` — 7 tests on per-agent budgets and
  filter propagation
- `tests/unit/test_drafter_with_memory.py` — 4 tests verifying the Drafter
  pulls memory when wired in
- `tests/integration/test_memory_recorder.py` — 4 integration tests against
  the test database verifying the three-tier commit order

## See also

- [Architecture: memory](../../docs/architecture/memory.md)
- [ADR-0002: Causal memory](../../docs/adr/0002-causal-memory.md)
- [ADR-0003: Dynamic context construction](../../docs/adr/0003-dynamic-context-construction.md)
