"""cascade memory layer.

Three concerns:

- **Causal memory** — structured Decision rows in Postgres with alternatives,
  tradeoffs, and evidence. Owned by :class:`cascade.storage.repositories.decision.DecisionRepository`.
- **Conversational memory** — vector-indexed transcript chunks in ChromaDB.
  Implemented by :class:`ChromaMemoryStore`.
- **Hybrid retrieval** — BM25 + dense + cross-encoder reranking, exposed through
  the :class:`Retriever` protocol.

The :class:`ContextBuilder` is the single entry point agents call when they need
context — it composes all three concerns into a single ``AssembledContext``.
"""

from cascade.memory.bm25 import BM25Index
from cascade.memory.context_builder import AssembledContext, ContextBuilder
from cascade.memory.fakes import (
    HashEmbedder,
    IdentityReranker,
    InMemoryStore,
    StaticRetriever,
)
from cascade.memory.recorder import CommitOutcome, MemoryRecorder
from cascade.memory.reranker import LLMReranker
from cascade.memory.retrieval import HybridRetriever
from cascade.memory.types import (
    Embedder,
    MemoryChunk,
    MemoryQuery,
    MemoryStore,
    Reranker,
    RetrievedChunk,
    Retriever,
)

__all__ = [
    "AssembledContext",
    "BM25Index",
    "ChromaMemoryStore",
    "CommitOutcome",
    "ContextBuilder",
    "Embedder",
    "HashEmbedder",
    "HybridRetriever",
    "IdentityReranker",
    "InMemoryStore",
    "LLMReranker",
    "MemoryChunk",
    "MemoryQuery",
    "MemoryRecorder",
    "MemoryStore",
    "Reranker",
    "RetrievedChunk",
    "Retriever",
    "StaticRetriever",
]


def __getattr__(name: str) -> object:
    """Lazy import for ChromaMemoryStore so importing cascade.memory doesn't pull in chromadb."""
    if name == "ChromaMemoryStore":
        from cascade.memory.store import ChromaMemoryStore as _ChromaMemoryStore

        return _ChromaMemoryStore
    raise AttributeError(f"module 'cascade.memory' has no attribute {name!r}")
