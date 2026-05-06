"""ChromaDB-backed implementation of :class:`MemoryStore`.

ChromaDB handles the dense vector index, metadata filtering, and persistence. We
wrap its async client behind the :class:`MemoryStore` protocol so the rest of the
codebase doesn't import ``chromadb`` directly — keeping the dependency surface
auditable and the swap path open.

The default collection uses ChromaDB's built-in embedding function, which runs an
ONNX MiniLM model in-process. No PyTorch dependency, no GPU requirement. For
deployments that want to plug in a different embedder, pass an :class:`Embedder`
to the constructor and we'll wrap it as ChromaDB's ``embedding_function``.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from cascade.memory.types import MemoryChunk, RetrievedChunk

if TYPE_CHECKING:
    from cascade.memory.types import Embedder

logger = logging.getLogger(__name__)


class _EmbedderAdapter:
    """Adapt a cascade :class:`Embedder` to ChromaDB's expected callable shape."""

    def __init__(self, embedder: Embedder) -> None:
        self._embedder = embedder

    def __call__(self, input: list[str]) -> list[list[float]]:
        # ChromaDB calls the embedding function with positional ``input`` — match
        # that exactly to avoid signature mismatches.
        return self._embedder.embed(input)

    def name(self) -> str:
        """ChromaDB requires this for embedding-function registry."""
        return self._embedder.__class__.__name__


class ChromaMemoryStore:
    """ChromaDB-backed memory store.

    Args:
        host: ChromaDB host (e.g. "localhost"). For an embedded/in-process client,
            pass ``None`` and a local ``persist_directory`` will be used.
        port: ChromaDB port.
        collection_name: The collection name within ChromaDB.
        embedder: Optional :class:`Embedder` override. If omitted, ChromaDB's
            default ONNX embedding function is used.
        persist_directory: For embedded clients only — where to write SQLite/HNSW
            files.
    """

    def __init__(
        self,
        *,
        host: str | None = None,
        port: int = 8000,
        collection_name: str = "cascade_memory",
        embedder: Embedder | None = None,
        persist_directory: str | None = None,
    ) -> None:
        # Imported lazily so cascade.memory.types doesn't need chromadb at import time.
        import chromadb

        if host:
            self._client = chromadb.HttpClient(host=host, port=port)
        elif persist_directory:
            self._client = chromadb.PersistentClient(path=persist_directory)
        else:
            self._client = chromadb.EphemeralClient()

        embedding_function: Any = None
        if embedder is not None:
            embedding_function = _EmbedderAdapter(embedder)

        self._collection = self._client.get_or_create_collection(
            name=collection_name,
            embedding_function=embedding_function,
            metadata={"hnsw:space": "cosine"},
        )

    async def add(self, chunks: list[MemoryChunk]) -> None:
        if not chunks:
            return
        ids = [c.id for c in chunks]
        documents = [c.text for c in chunks]
        metadatas = [dict(c.metadata) for c in chunks]
        # ChromaDB upserts by id, so re-adding a chunk is a no-op idempotent update.
        self._collection.upsert(ids=ids, documents=documents, metadatas=metadatas)

    async def search_dense(
        self,
        *,
        query: str,
        filters: dict[str, str] | None = None,
        limit: int = 10,
    ) -> list[RetrievedChunk]:
        where = self._to_where(filters)
        result = self._collection.query(
            query_texts=[query],
            n_results=limit,
            where=where,
        )
        return self._unpack_query_result(result)

    async def get(self, chunk_id: str) -> MemoryChunk | None:
        result = self._collection.get(ids=[chunk_id], include=["documents", "metadatas"])
        if not result["ids"]:
            return None
        return MemoryChunk(
            id=result["ids"][0],
            text=result["documents"][0],
            metadata=dict(result["metadatas"][0] or {}),
        )

    async def delete(self, chunk_ids: list[str]) -> None:
        if not chunk_ids:
            return
        self._collection.delete(ids=chunk_ids)

    @staticmethod
    def _to_where(filters: dict[str, str] | None) -> dict[str, Any] | None:
        """Translate ``{"k": "v"}`` to ChromaDB's where DSL.

        ChromaDB requires ``$and`` for multi-key filters; single-key filters are
        passed as-is.
        """
        if not filters:
            return None
        if len(filters) == 1:
            key, value = next(iter(filters.items()))
            return {key: value}
        return {"$and": [{k: v} for k, v in filters.items()]}

    @staticmethod
    def _unpack_query_result(result: dict[str, Any]) -> list[RetrievedChunk]:
        ids = result.get("ids", [[]])[0]
        documents = result.get("documents", [[]])[0]
        metadatas = result.get("metadatas", [[]])[0]
        distances = result.get("distances", [[]])[0]

        out: list[RetrievedChunk] = []
        for chunk_id, doc, meta, dist in zip(ids, documents, metadatas, distances, strict=True):
            # ChromaDB returns cosine distance (lower is closer); convert to similarity.
            score = 1.0 - float(dist)
            chunk = MemoryChunk(id=chunk_id, text=doc, metadata=dict(meta or {}))
            out.append(RetrievedChunk(chunk=chunk, score=score, source="dense"))
        return out
