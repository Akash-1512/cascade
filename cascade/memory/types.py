"""Protocols and value types for the memory layer.

Three orthogonal concepts the memory layer needs:

- :class:`Embedder` — turns text into dense vectors. The production implementation
  uses ONNX MiniLM via ChromaDB's default embedding function. Tests inject a
  deterministic hash-based embedder.
- :class:`Reranker` — re-orders a candidate list using a cross-encoder pattern. The
  production implementation uses an LLM as the cross-encoder; tests inject identity
  reranking.
- :class:`Retriever` — the boundary the agents call. Hybrid retrieval orchestrates
  BM25, dense search, and reranking under this single interface.

Keeping these as protocols lets us swap implementations without touching agent code
— the same agent runs against fakes in tests, MiniLM in development, and a tuned
cross-encoder in production.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class MemoryChunk(BaseModel):
    """A single retrievable unit of conversational memory.

    ``text`` is what gets embedded and matched. ``metadata`` carries the structural
    pointers the agents use to resolve a chunk back to its OKR, decision, or
    transcript context.
    """

    model_config = ConfigDict(extra="forbid")

    id: str = Field(min_length=1, max_length=200)
    text: str = Field(min_length=1)
    metadata: dict[str, str | int | float | bool] = Field(default_factory=dict)


class RetrievedChunk(BaseModel):
    """A chunk returned from retrieval, paired with its score."""

    model_config = ConfigDict(extra="forbid")

    chunk: MemoryChunk
    score: float = Field(description="Higher is more relevant. Not constrained to [0,1].")
    source: str = Field(
        description="Which retrieval stage scored this — 'bm25', 'dense', 'rerank'.",
    )


class MemoryQuery(BaseModel):
    """A retrieval request scoped by metadata filters."""

    model_config = ConfigDict(extra="forbid")

    query: str = Field(min_length=1)
    okr_id: UUID | None = None
    team_id: UUID | None = None
    kind: str | None = Field(
        default=None,
        description="Filter by chunk kind: 'drafting', 'checkin', 'retro', 'risk_review'.",
    )
    quarter: str | None = Field(
        default=None,
        pattern=r"^\d{4}Q[1-4]$",
        description="Filter to a specific quarter, e.g. '2026Q2'.",
    )
    limit: int = Field(default=5, ge=1, le=50)


@runtime_checkable
class Embedder(Protocol):
    """Embeds text into dense vectors.

    Implementations must be deterministic for a given input — the same text always
    embeds to the same vector. ChromaDB caches by hash so non-determinism causes
    silent duplicate inserts.
    """

    @property
    def dimensions(self) -> int:
        """The dimensionality of the produced vectors."""
        ...

    def embed(self, texts: list[str]) -> list[list[float]]:
        """Embed a batch of texts. Order is preserved."""
        ...


@runtime_checkable
class Reranker(Protocol):
    """Re-orders candidate chunks using a cross-encoder pattern.

    Cross-encoders score the (query, passage) pair jointly and tend to produce
    better ranking than the dense vector cosine on its own — at the cost of latency
    that's roughly N times the encoding cost for N candidates. The reranker is
    therefore applied to the union of BM25 and dense top-K, not to the entire
    corpus.
    """

    async def rerank(
        self,
        *,
        query: str,
        chunks: list[MemoryChunk],
    ) -> list[RetrievedChunk]:
        """Score each chunk against the query and return them sorted descending."""
        ...


@runtime_checkable
class Retriever(Protocol):
    """The retrieval boundary that agents call.

    Hides whether the underlying implementation is BM25-only, dense-only, or hybrid
    — the agents do not care.
    """

    async def search(self, query: MemoryQuery) -> list[RetrievedChunk]:
        """Retrieve the top-K chunks matching the query."""
        ...


@runtime_checkable
class MemoryStore(Protocol):
    """The persistence boundary for memory chunks."""

    async def add(self, chunks: list[MemoryChunk]) -> None:
        """Add chunks to the store. Idempotent on chunk id."""
        ...

    async def search_dense(
        self,
        *,
        query: str,
        filters: dict[str, str] | None = None,
        limit: int = 10,
    ) -> list[RetrievedChunk]:
        """Dense vector search with optional metadata filters."""
        ...

    async def get(self, chunk_id: str) -> MemoryChunk | None:
        """Fetch a chunk by id. Returns ``None`` if not found."""
        ...

    async def delete(self, chunk_ids: list[str]) -> None:
        """Delete chunks by id. Missing ids are silently ignored."""
        ...
