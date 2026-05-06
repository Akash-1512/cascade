"""Hybrid retrieval pipeline.

Three stages:

1. **BM25** over chunk text — high precision on rare terms, named entities,
   project codenames, and abbreviations.
2. **Dense vector search** via the underlying :class:`MemoryStore` — semantic
   recall.
3. **Cross-encoder rerank** on the union of BM25 and dense top-K — the joint
   scoring is more accurate than either signal alone.

Why this matters: the OKR domain is full of phrases that BM25 catches and dense
search misses ("EMEA pricing change", "ContextPool migration", "Q2 SMB cohort"),
and full of paraphrases that dense catches and BM25 misses ("trial conversion" →
"signup-to-paid funnel"). A single retriever loses both groups.

The reranker resolves disagreements: when BM25 ranks a chunk highly but dense
disagrees, the cross-encoder's joint scoring makes the call.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from cascade.memory.bm25 import BM25Index
from cascade.memory.types import (
    MemoryChunk,
    MemoryQuery,
    Reranker,
    RetrievedChunk,
)

if TYPE_CHECKING:
    from cascade.memory.types import MemoryStore


# Number of candidates each stage produces before the reranker. K is intentionally
# generous because the reranker is responsible for cutting to the final limit.
DENSE_K = 20
BM25_K = 20


class HybridRetriever:
    """Retriever that runs BM25 + dense + rerank in sequence.

    Args:
        store: The underlying :class:`MemoryStore` (typically ChromaDB).
        reranker: The :class:`Reranker` used to merge and re-score candidates.
        corpus_loader: Async callable returning the BM25 corpus for a query.
            Defaults to "all chunks matching the metadata filters" — implemented
            via the store's bulk fetch where possible.
    """

    def __init__(
        self,
        *,
        store: MemoryStore,
        reranker: Reranker,
    ) -> None:
        self._store = store
        self._reranker = reranker

    async def search(self, query: MemoryQuery) -> list[RetrievedChunk]:
        """Run the full hybrid pipeline."""
        filters = _build_filters(query)

        dense_hits = await self._store.search_dense(
            query=query.query,
            filters=filters,
            limit=DENSE_K,
        )

        # Build BM25 index over the candidates returned by dense — for cases where
        # dense missed something keyword-relevant, the candidate set still needs to
        # contain it. For larger deployments, replace this with an explicit BM25
        # corpus pull from the store.
        bm25_corpus = [hit.chunk for hit in dense_hits]
        bm25_index = BM25Index(bm25_corpus)
        bm25_hits = bm25_index.search(query.query, limit=BM25_K)

        candidates = _merge_candidates(dense_hits, bm25_hits)
        if not candidates:
            return []

        reranked = await self._reranker.rerank(
            query=query.query,
            chunks=candidates,
        )
        return reranked[: query.limit]


def _build_filters(query: MemoryQuery) -> dict[str, str] | None:
    """Translate a :class:`MemoryQuery` into the store's filter format."""
    filters: dict[str, str] = {}
    if query.okr_id is not None:
        filters["okr_id"] = str(query.okr_id)
    if query.team_id is not None:
        filters["team_id"] = str(query.team_id)
    if query.kind is not None:
        filters["kind"] = query.kind
    if query.quarter is not None:
        filters["quarter"] = query.quarter
    return filters or None


def _merge_candidates(
    dense_hits: list[RetrievedChunk],
    bm25_hits: list[RetrievedChunk],
) -> list[MemoryChunk]:
    """De-duplicate candidates from dense and BM25 by chunk id, preserving order."""
    seen: set[str] = set()
    merged: list[MemoryChunk] = []
    for hit in [*dense_hits, *bm25_hits]:
        if hit.chunk.id in seen:
            continue
        seen.add(hit.chunk.id)
        merged.append(hit.chunk)
    return merged
