"""Deterministic in-memory fakes for the memory protocols.

These exist so unit tests don't need ChromaDB, ONNX runtime, or any model weights.
They are also the cheapest way to read what the protocols promise — if a fake
implements them, the contract is small enough to grasp.
"""

from __future__ import annotations

import hashlib
import math

from cascade.memory.types import (
    MemoryChunk,
    MemoryQuery,
    RetrievedChunk,
)


class HashEmbedder:
    """Deterministic hash-based embedder.

    Given a text, returns a 64-dimensional vector derived from MD5. Has no semantic
    properties — two paraphrases produce unrelated vectors. Useful only for
    plumbing tests that verify the right calls happen at the right time.
    """

    @property
    def dimensions(self) -> int:
        return 64

    def embed(self, texts: list[str]) -> list[list[float]]:
        return [self._embed_one(t) for t in texts]

    def _embed_one(self, text: str) -> list[float]:
        digest = hashlib.md5(text.encode("utf-8"), usedforsecurity=False).digest()
        # Expand 16 bytes into 64 floats by repeating; normalise to unit length.
        raw = [b / 255.0 for b in digest] * 4
        norm = math.sqrt(sum(x * x for x in raw)) or 1.0
        return [x / norm for x in raw]


class IdentityReranker:
    """Reranker that preserves input order and assigns score = -position.

    Useful when you want to test downstream code paths without LLM variance. Score
    is negative so that higher scores still mean "earlier in the list" — matching
    the contract that retrievers use.
    """

    async def rerank(
        self,
        *,
        query: str,
        chunks: list[MemoryChunk],
    ) -> list[RetrievedChunk]:
        return [
            RetrievedChunk(chunk=chunk, score=-float(i), source="rerank")
            for i, chunk in enumerate(chunks)
        ]


class InMemoryStore:
    """In-memory implementation of :class:`MemoryStore`.

    Keeps chunks in a dict, applies filters as plain Python comparisons, and uses
    cosine similarity over the injected :class:`Embedder`. Faster than ChromaDB
    for tests and free of any startup cost.
    """

    def __init__(self, embedder: HashEmbedder) -> None:
        self._embedder = embedder
        self._chunks: dict[str, MemoryChunk] = {}
        self._vectors: dict[str, list[float]] = {}

    async def add(self, chunks: list[MemoryChunk]) -> None:
        if not chunks:
            return
        vectors = self._embedder.embed([c.text for c in chunks])
        for chunk, vec in zip(chunks, vectors, strict=True):
            self._chunks[chunk.id] = chunk
            self._vectors[chunk.id] = vec

    async def search_dense(
        self,
        *,
        query: str,
        filters: dict[str, str] | None = None,
        limit: int = 10,
    ) -> list[RetrievedChunk]:
        if not self._chunks:
            return []
        query_vec = self._embedder.embed([query])[0]
        scored: list[RetrievedChunk] = []
        for chunk_id, chunk in self._chunks.items():
            if filters and not self._matches_filters(chunk, filters):
                continue
            score = _cosine(query_vec, self._vectors[chunk_id])
            scored.append(RetrievedChunk(chunk=chunk, score=score, source="dense"))
        scored.sort(key=lambda r: r.score, reverse=True)
        return scored[:limit]

    async def get(self, chunk_id: str) -> MemoryChunk | None:
        return self._chunks.get(chunk_id)

    async def delete(self, chunk_ids: list[str]) -> None:
        for chunk_id in chunk_ids:
            self._chunks.pop(chunk_id, None)
            self._vectors.pop(chunk_id, None)

    @property
    def size(self) -> int:
        """Number of chunks currently stored — handy for tests."""
        return len(self._chunks)

    @staticmethod
    def _matches_filters(chunk: MemoryChunk, filters: dict[str, str]) -> bool:
        return all(chunk.metadata.get(key) == value for key, value in filters.items())


class StaticRetriever:
    """A retriever that returns a pre-configured response regardless of query.

    Lets tests of agents and the context builder run without standing up the full
    retrieval pipeline.
    """

    def __init__(self, results: list[RetrievedChunk]) -> None:
        self._results = list(results)
        self.calls: list[MemoryQuery] = []

    async def search(self, query: MemoryQuery) -> list[RetrievedChunk]:
        self.calls.append(query)
        return list(self._results[: query.limit])


def _cosine(a: list[float], b: list[float]) -> float:
    """Cosine similarity between two equal-length vectors."""
    dot = sum(x * y for x, y in zip(a, b, strict=True))
    na = math.sqrt(sum(x * x for x in a)) or 1.0
    nb = math.sqrt(sum(x * x for x in b)) or 1.0
    return dot / (na * nb)
