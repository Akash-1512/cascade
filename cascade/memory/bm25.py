"""BM25 keyword index for hybrid retrieval.

BM25 covers the cases where dense embeddings underperform: rare terms, exact named
entities, project codenames, and domain-specific abbreviations. The hybrid retriever
unions BM25's top-K with dense's top-K and reranks the result.

The index is rebuilt in-process from the chunk corpus on each query — for the
volumes cascade handles (thousands of chunks per tenant), this is fast enough that
the simplicity of "no separate index store to keep consistent" wins over latency.
For larger deployments, swap in an Elasticsearch-backed implementation behind the
same call signature.
"""

from __future__ import annotations

import re

from rank_bm25 import BM25Okapi

from cascade.memory.types import MemoryChunk, RetrievedChunk

_TOKEN_PATTERN = re.compile(r"[a-z0-9]+")


def _tokenise(text: str) -> list[str]:
    """Lowercase and split on non-alphanumerics. Stable, dependency-free."""
    return _TOKEN_PATTERN.findall(text.lower())


class BM25Index:
    """Lightweight in-memory BM25 wrapper.

    Build once from a corpus of chunks, query many times. For volatile corpora,
    rebuild on each search — :func:`HybridRetriever.search` does this.
    """

    def __init__(self, chunks: list[MemoryChunk]) -> None:
        self._chunks = chunks
        self._tokenised = [_tokenise(c.text) for c in chunks]
        # rank_bm25 raises on empty corpora; guard so callers don't have to.
        self._bm25: BM25Okapi | None = BM25Okapi(self._tokenised) if self._tokenised else None

    def search(self, query: str, *, limit: int = 10) -> list[RetrievedChunk]:
        """Return the top-``limit`` chunks by BM25 score, descending."""
        if self._bm25 is None:
            return []
        tokens = _tokenise(query)
        if not tokens:
            return []
        scores = self._bm25.get_scores(tokens)
        ranked = sorted(
            zip(self._chunks, scores, strict=True),
            key=lambda pair: pair[1],
            reverse=True,
        )
        return [
            RetrievedChunk(chunk=chunk, score=float(score), source="bm25")
            for chunk, score in ranked[:limit]
            if score > 0.0  # rank_bm25 can produce negative or zero scores; drop them
        ]
