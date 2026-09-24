"""Embedding + reranking for document RAG, via Pinecone Inference.

The spec names nomic-embed-text (dense), pinecone-text SPLADE/BM25 (sparse)
and a local bge-reranker-base cross-encoder. None of those run here (no
torch, no model hosting); all three roles are served by the Pinecone key the
project already has, with no local model weights:

- dense:  llama-text-embed-v2 at 768 dims (same dimension as agent memory)
- sparse: pinecone-sparse-english-v0 (hosted learned-sparse lexical model --
          fills the BM25/SPLADE role without fitting a corpus vocabulary)
- rerank: bge-reranker-v2-m3 (hosted cross-encoder, successor of bge-reranker-base)
"""

from __future__ import annotations

import logging
from typing import Any, Literal, Protocol

logger = logging.getLogger("fleet.rag")

InputType = Literal["passage", "query"]
_BATCH = 96  # Pinecone Inference's per-request input limit for these models


class RagInference(Protocol):
    def embed_dense(self, texts: list[str], input_type: InputType) -> list[list[float]]: ...
    def embed_sparse(self, texts: list[str], input_type: InputType) -> list[dict[str, list]]: ...
    def rerank(self, query: str, documents: list[str]) -> list[tuple[int, float]]: ...


class PineconeRagInference:
    def __init__(self, client: Any, *, dense_model: str, sparse_model: str, rerank_model: str, dimension: int) -> None:
        self.client = client
        self.dense_model = dense_model
        self.sparse_model = sparse_model
        self.rerank_model = rerank_model
        self.dimension = dimension

    def embed_dense(self, texts, input_type):
        vectors: list[list[float]] = []
        for start in range(0, len(texts), _BATCH):
            result = self.client.inference.embed(
                model=self.dense_model,
                inputs=texts[start : start + _BATCH],
                parameters={"input_type": input_type, "dimension": self.dimension, "truncate": "END"},
            )
            vectors.extend(list(item.values) for item in result)
        return vectors

    def embed_sparse(self, texts, input_type):
        vectors: list[dict[str, list]] = []
        for start in range(0, len(texts), _BATCH):
            result = self.client.inference.embed(
                model=self.sparse_model,
                inputs=texts[start : start + _BATCH],
                parameters={"input_type": input_type, "truncate": "END"},
            )
            vectors.extend(
                {"indices": list(item.sparse_indices), "values": list(item.sparse_values)} for item in result
            )
        return vectors

    def rerank(self, query, documents):
        if not documents:
            return []
        result = self.client.inference.rerank(
            model=self.rerank_model, query=query, documents=documents, top_n=len(documents), return_documents=False
        )
        return [(row.index, float(row.score)) for row in result.data]


def hybrid_scale(dense: list[float], sparse: dict[str, list], alpha: float) -> tuple[list[float], dict[str, list]]:
    """Convex combination for a dotproduct index: score = alpha*dense_score +
    (1-alpha)*sparse_score is achieved by scaling the two query parts."""
    if not 0.0 <= alpha <= 1.0:
        raise ValueError("alpha must be within [0, 1]")
    return (
        [v * alpha for v in dense],
        {"indices": list(sparse["indices"]), "values": [v * (1 - alpha) for v in sparse["values"]]},
    )


_inference: RagInference | None = None
_initialized = False


def get_rag_inference() -> RagInference | None:
    """None without PINECONE_API_KEY -- document RAG is then unavailable (503),
    since there is no meaningful keyword-only fallback for a vector corpus
    that was never indexed."""
    global _inference, _initialized
    if not _initialized:
        from app.core.config import get_settings
        from app.models.memory import EMBEDDING_DIM

        settings = get_settings()
        if settings.pinecone_api_key:
            from pinecone import Pinecone

            _inference = PineconeRagInference(
                Pinecone(api_key=settings.pinecone_api_key),
                dense_model=settings.rag_dense_model,
                sparse_model=settings.rag_sparse_model,
                rerank_model=settings.rag_rerank_model,
                dimension=EMBEDDING_DIM,
            )
        _initialized = True
    return _inference


def set_rag_inference(inference: RagInference | None) -> None:
    global _inference, _initialized
    _inference = inference
    _initialized = True
