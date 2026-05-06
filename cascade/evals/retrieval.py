"""Retrieval eval — measures hybrid retrieval precision and recall.

For each :class:`MemoryQueryCase`:

1. Build an :class:`InMemoryStore` from the case's ``context_chunks`` only
2. Wrap with :class:`HybridRetriever` using :class:`IdentityReranker` (deterministic)
3. Run the query
4. Compute precision and recall against ``expected_relevant_ids``

This is intentionally cheaper than RAGAS — RAGAS makes additional LLM calls per
case for faithfulness, which is overkill when retrieval correctness is the
gate. We use a simple set-overlap metric here and let RAGAS run as a separate
optional eval (see ``ragas`` extra in pyproject) for deeper analysis.
"""

from __future__ import annotations

import time

from cascade.evals.datasets import MemoryQueryCase
from cascade.evals.types import CaseResult, MetricResult
from cascade.memory.fakes import HashEmbedder, IdentityReranker, InMemoryStore
from cascade.memory.retrieval import HybridRetriever
from cascade.memory.types import MemoryChunk, MemoryQuery


async def evaluate_retrieval(
    *,
    cases: list[MemoryQueryCase],
    threshold: float,
) -> MetricResult:
    """Run retrieval evaluation over the cases.

    The score returned is **mean F1 across cases** — balances precision and
    recall in one number. Per-case results record both individually for the
    threshold checker's PR comment.
    """
    results: list[CaseResult] = []
    started = time.monotonic()

    sum_precision = 0.0
    sum_recall = 0.0

    for case in cases:
        store = InMemoryStore(HashEmbedder())
        chunks = [
            MemoryChunk(id=c.id, text=c.text, metadata=dict(c.metadata))
            for c in case.context_chunks
        ]
        await store.add(chunks)

        retriever = HybridRetriever(store=store, reranker=IdentityReranker())
        retrieved = await retriever.search(
            MemoryQuery(query=case.query, limit=len(case.context_chunks))
        )
        retrieved_ids = {hit.chunk.id for hit in retrieved}
        expected_ids = set(case.expected_relevant_ids)

        # Limit retrieved set to top-K where K = number of relevant chunks
        # (standard precision-at-K convention).
        k = len(expected_ids)
        top_k_ids = {hit.chunk.id for hit in retrieved[:k]}

        tp = len(top_k_ids & expected_ids)
        precision = tp / max(1, len(top_k_ids))
        recall = tp / max(1, len(expected_ids))
        f1 = 2 * precision * recall / (precision + recall) if (precision + recall) > 0 else 0.0

        sum_precision += precision
        sum_recall += recall

        results.append(
            CaseResult(
                case_id=case.id,
                passed=f1 >= threshold,
                score=f1,
                expected=",".join(sorted(expected_ids)),
                actual=",".join(sorted(top_k_ids)),
                notes=f"precision={precision:.2f} recall={recall:.2f} retrieved={len(retrieved_ids)}",
            )
        )

    n = max(1, len(results))
    mean_f1 = sum(r.score for r in results) / n
    elapsed = time.monotonic() - started

    return MetricResult(
        name="retrieval_f1",
        score=mean_f1,
        threshold=threshold,
        cases=results,
        metadata={
            "total_cases": len(results),
            "elapsed_seconds": round(elapsed, 2),
            "mean_precision": round(sum_precision / n, 3),
            "mean_recall": round(sum_recall / n, 3),
        },
    )
