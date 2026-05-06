"""LLM-based cross-encoder reranker.

Cross-encoders score a (query, passage) pair jointly. A trained encoder model is
the conventional implementation; this module uses an LLM as the scorer instead,
which trades latency for not requiring a separate model deployment.

The trade-off is explicit: ``LLMReranker`` is fine for tens of candidates per
query, slow at hundreds, prohibitive at thousands. For volumes beyond that, plug a
``Reranker`` that wraps an ONNX cross-encoder model behind the same Protocol.
"""

from __future__ import annotations

import json
import logging
from typing import TYPE_CHECKING

from cascade.memory.types import MemoryChunk, RetrievedChunk

if TYPE_CHECKING:
    from langchain_core.language_models import BaseChatModel

logger = logging.getLogger(__name__)


_RERANK_PROMPT = """You are a relevance scorer. Given a query and a list of passages,
score each passage from 0.0 to 1.0 for how relevant it is to the query.

A score of 1.0 means the passage directly answers or supports the query.
A score of 0.5 means the passage is on the same topic but not directly relevant.
A score of 0.0 means the passage is unrelated.

Query: {query}

Passages:
{passages}

Return ONLY a JSON array of {n} numbers in the same order as the passages, each
between 0.0 and 1.0. No prose, no commentary, no markdown fences.

Example output for 3 passages: [0.9, 0.2, 0.7]
"""


class LLMReranker:
    """Reranker that uses the chat model to score (query, chunk) pairs.

    Args:
        model: The chat model to use for scoring.
        batch_size: Maximum chunks per LLM call. Above this the chunks are split
            into multiple calls and the resulting scores concatenated.
    """

    def __init__(
        self,
        *,
        model: BaseChatModel,
        batch_size: int = 10,
    ) -> None:
        self._model = model
        self._batch_size = batch_size

    async def rerank(
        self,
        *,
        query: str,
        chunks: list[MemoryChunk],
    ) -> list[RetrievedChunk]:
        if not chunks:
            return []

        scores: list[float] = []
        for i in range(0, len(chunks), self._batch_size):
            batch = chunks[i : i + self._batch_size]
            batch_scores = await self._score_batch(query, batch)
            scores.extend(batch_scores)

        results = [
            RetrievedChunk(chunk=chunk, score=score, source="rerank")
            for chunk, score in zip(chunks, scores, strict=True)
        ]
        results.sort(key=lambda r: r.score, reverse=True)
        return results

    async def _score_batch(
        self,
        query: str,
        batch: list[MemoryChunk],
    ) -> list[float]:
        passages = "\n\n".join(f"[{i}] {chunk.text}" for i, chunk in enumerate(batch, start=1))
        prompt = _RERANK_PROMPT.format(query=query, passages=passages, n=len(batch))

        try:
            response = await self._model.ainvoke(prompt)
            text = response.content if hasattr(response, "content") else response
            return self._parse_scores(text, expected=len(batch))
        except Exception as exc:
            # Fallback: equal-weight scoring preserves input order without crashing.
            logger.warning("LLMReranker scoring failed, returning neutral scores: %s", exc)
            return [0.5] * len(batch)

    @staticmethod
    def _parse_scores(text: str | object, *, expected: int) -> list[float]:
        if not isinstance(text, str):
            raise ValueError(f"unexpected reranker response type: {type(text).__name__}")

        cleaned = text.strip()
        if cleaned.startswith("```"):
            lines = cleaned.splitlines()
            cleaned = "\n".join(lines[1:-1] if lines[-1].startswith("```") else lines[1:])

        parsed = json.loads(cleaned)
        if not isinstance(parsed, list) or len(parsed) != expected:
            raise ValueError(f"expected {expected} scores, got {parsed}")

        return [max(0.0, min(1.0, float(s))) for s in parsed]
