"""Tests for the memory primitives."""

from __future__ import annotations

import json

import pytest

from cascade.agents.llm import FakeChatModel
from cascade.memory.bm25 import BM25Index
from cascade.memory.fakes import (
    HashEmbedder,
    IdentityReranker,
    InMemoryStore,
    StaticRetriever,
)
from cascade.memory.reranker import LLMReranker
from cascade.memory.retrieval import HybridRetriever
from cascade.memory.types import MemoryChunk, MemoryQuery, RetrievedChunk


def _chunks(*specs: tuple[str, str, dict[str, str]]) -> list[MemoryChunk]:
    """Construct a small batch of chunks for tests.

    Each spec is ``(id, text, metadata)``.
    """
    return [MemoryChunk(id=cid, text=text, metadata=meta) for cid, text, meta in specs]


# --- HashEmbedder -----------------------------------------------------------


@pytest.mark.unit
def test_hash_embedder_dimensions() -> None:
    e = HashEmbedder()
    assert e.dimensions == 64
    [vec] = e.embed(["hello"])
    assert len(vec) == 64


@pytest.mark.unit
def test_hash_embedder_is_deterministic() -> None:
    e = HashEmbedder()
    [a] = e.embed(["the same text"])
    [b] = e.embed(["the same text"])
    assert a == b


@pytest.mark.unit
def test_hash_embedder_normalised() -> None:
    """Each vector should be approximately unit-length so cosine works."""
    e = HashEmbedder()
    [vec] = e.embed(["any text"])
    norm = sum(x * x for x in vec) ** 0.5
    assert 0.99 < norm < 1.01


# --- BM25 -------------------------------------------------------------------


@pytest.mark.unit
def test_bm25_returns_top_match() -> None:
    chunks = _chunks(
        ("a", "We discussed EMEA pricing changes for the Q2 launch", {}),
        ("b", "The team agreed to lower the SMB onboarding target", {}),
        ("c", "Pipeline review showed 18% growth in trial conversion", {}),
    )
    index = BM25Index(chunks)
    hits = index.search("EMEA pricing")
    assert hits[0].chunk.id == "a"
    assert hits[0].source == "bm25"


@pytest.mark.unit
def test_bm25_empty_corpus_returns_empty() -> None:
    index = BM25Index([])
    assert index.search("anything") == []


@pytest.mark.unit
def test_bm25_empty_query_returns_empty() -> None:
    index = BM25Index(_chunks(("a", "some text", {})))
    assert index.search("") == []


@pytest.mark.unit
def test_bm25_drops_zero_scores() -> None:
    """Chunks with no matching tokens should not appear in results.

    BM25 IDF is poorly defined on tiny corpora — use 5 docs so IDF math gives
    meaningful weights on the unique terms.
    """
    chunks = _chunks(
        ("a", "completely unrelated content here", {}),
        ("b", "rare-codename-xyz appears here in this passage", {}),
        ("c", "another piece of generic text content", {}),
        ("d", "yet more boilerplate writing about generic topics", {}),
        ("e", "padding text to give the corpus enough mass", {}),
    )
    hits = BM25Index(chunks).search("rare-codename-xyz")
    assert len(hits) == 1
    assert hits[0].chunk.id == "b"


# --- InMemoryStore ----------------------------------------------------------


@pytest.mark.unit
async def test_inmemory_store_add_and_search() -> None:
    store = InMemoryStore(HashEmbedder())
    chunks = _chunks(
        ("a", "first chunk text", {"team_id": "team-1"}),
        ("b", "second chunk text", {"team_id": "team-2"}),
    )
    await store.add(chunks)
    assert store.size == 2

    results = await store.search_dense(query="first chunk text", limit=2)
    assert results[0].chunk.id == "a"


@pytest.mark.unit
async def test_inmemory_store_metadata_filter() -> None:
    store = InMemoryStore(HashEmbedder())
    chunks = _chunks(
        ("a", "text alpha", {"team_id": "team-1"}),
        ("b", "text beta", {"team_id": "team-2"}),
    )
    await store.add(chunks)

    results = await store.search_dense(query="text", filters={"team_id": "team-1"}, limit=10)
    assert {r.chunk.id for r in results} == {"a"}


@pytest.mark.unit
async def test_inmemory_store_get_and_delete() -> None:
    store = InMemoryStore(HashEmbedder())
    await store.add(_chunks(("a", "one", {}), ("b", "two", {})))
    assert (await store.get("a")) is not None
    await store.delete(["a"])
    assert (await store.get("a")) is None
    assert store.size == 1


# --- HybridRetriever --------------------------------------------------------


@pytest.mark.unit
async def test_hybrid_retriever_combines_signals() -> None:
    """The hybrid retriever returns results from both signals.

    HashEmbedder has no semantic meaning, so this test verifies the plumbing —
    the retriever runs the full pipeline, applies the reranker, and returns
    structured results. Real semantic-relevance tests run against ChromaDB in the
    integration suite.
    """
    store = InMemoryStore(HashEmbedder())
    chunks = _chunks(
        ("a", "EMEA pricing policy was raised to 12% in Q1 2026", {"kind": "drafting"}),
        ("b", "SMB churn is 6% across the trial cohort", {"kind": "drafting"}),
        ("c", "EMEA expansion delayed to Q3 pending headcount", {"kind": "drafting"}),
        ("d", "Product team agreed to ship onboarding changes", {"kind": "drafting"}),
    )
    await store.add(chunks)

    retriever = HybridRetriever(store=store, reranker=IdentityReranker())
    results = await retriever.search(MemoryQuery(query="EMEA pricing", limit=3))

    assert 0 < len(results) <= 3
    # All results are reranked (the final stage)
    assert all(r.source == "rerank" for r in results)


@pytest.mark.unit
async def test_hybrid_retriever_empty_store_returns_empty() -> None:
    store = InMemoryStore(HashEmbedder())
    retriever = HybridRetriever(store=store, reranker=IdentityReranker())
    results = await retriever.search(MemoryQuery(query="anything"))
    assert results == []


@pytest.mark.unit
async def test_hybrid_retriever_respects_limit() -> None:
    store = InMemoryStore(HashEmbedder())
    chunks = _chunks(*((f"id-{i}", f"text {i} EMEA pricing", {}) for i in range(20)))
    await store.add(chunks)
    retriever = HybridRetriever(store=store, reranker=IdentityReranker())
    results = await retriever.search(MemoryQuery(query="EMEA pricing", limit=5))
    assert len(results) == 5


# --- LLMReranker ------------------------------------------------------------


@pytest.mark.unit
async def test_llm_reranker_orders_by_score() -> None:
    chunks = _chunks(
        ("a", "passage one", {}),
        ("b", "passage two", {}),
        ("c", "passage three", {}),
    )
    model = FakeChatModel(responses=[json.dumps([0.2, 0.9, 0.5])])
    reranker = LLMReranker(model=model)

    results = await reranker.rerank(query="q", chunks=chunks)
    assert [r.chunk.id for r in results] == ["b", "c", "a"]
    assert all(r.source == "rerank" for r in results)


@pytest.mark.unit
async def test_llm_reranker_clamps_scores() -> None:
    chunks = _chunks(("a", "passage", {}))
    model = FakeChatModel(responses=[json.dumps([1.7])])  # out of range
    reranker = LLMReranker(model=model)
    results = await reranker.rerank(query="q", chunks=chunks)
    assert results[0].score == 1.0


@pytest.mark.unit
async def test_llm_reranker_falls_back_on_bad_response() -> None:
    chunks = _chunks(("a", "p1", {}), ("b", "p2", {}))
    model = FakeChatModel(responses=["not a json array"])
    reranker = LLMReranker(model=model)
    results = await reranker.rerank(query="q", chunks=chunks)
    # Falls back to neutral 0.5 scores; both pass through
    assert len(results) == 2
    assert all(r.score == 0.5 for r in results)


@pytest.mark.unit
async def test_llm_reranker_empty_chunks() -> None:
    model = FakeChatModel(responses=[])
    reranker = LLMReranker(model=model)
    assert await reranker.rerank(query="q", chunks=[]) == []


@pytest.mark.unit
async def test_llm_reranker_strips_markdown_fences() -> None:
    chunks = _chunks(("a", "p1", {}))
    fenced = "```json\n[0.6]\n```"
    model = FakeChatModel(responses=[fenced])
    reranker = LLMReranker(model=model)
    results = await reranker.rerank(query="q", chunks=chunks)
    assert results[0].score == pytest.approx(0.6)


# --- StaticRetriever --------------------------------------------------------


@pytest.mark.unit
async def test_static_retriever_records_calls() -> None:
    fixed = [
        RetrievedChunk(
            chunk=MemoryChunk(id="x", text="text"),
            score=0.9,
            source="rerank",
        ),
    ]
    retriever = StaticRetriever(fixed)
    result = await retriever.search(MemoryQuery(query="q", limit=5))
    assert result == fixed
    assert len(retriever.calls) == 1
    assert retriever.calls[0].query == "q"
