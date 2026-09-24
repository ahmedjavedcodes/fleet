"""Embedding providers for agent memory (agent-memory.md §2B).

The spec fixes the model -- nomic-embed-text-v1.5, 768 dimensions, explicitly
not OpenAI -- but nothing in this project runs it yet (no Ollama install, no
Nomic key, and Groq serves no embedding models). So the provider is chosen by
MEMORY_EMBEDDER and defaults to "none": memory still works end to end
(sessions, summaries, HITL-gated facts, scope-filtered and keyword recall),
only similarity ranking and similarity-based staleness are skipped until a
provider is configured. No fake embedding is ever produced -- a made-up
vector would silently corrupt every similarity comparison stored against it.
"""

from __future__ import annotations

import os
from typing import Literal, Protocol

import httpx

EMBEDDING_DIM = 768

TaskType = Literal["search_document", "search_query"]


class EmbeddingError(Exception):
    pass


class Embedder(Protocol):
    def embed(self, text: str, *, task: TaskType) -> list[float] | None: ...


def _check_dim(vector: list[float]) -> list[float]:
    if len(vector) != EMBEDDING_DIM:
        raise EmbeddingError(f"expected a {EMBEDDING_DIM}-dim embedding, got {len(vector)}")
    return vector


class NullEmbedder:
    """No provider configured: always None, never raises."""

    def embed(self, text: str, *, task: TaskType) -> list[float] | None:
        return None


class OllamaEmbedder:
    """nomic-embed-text served by a local/self-hosted Ollama. Nomic models
    expect the task as a text prefix ("search_document: ..."); Ollama passes
    the input through verbatim, so the prefix is added here."""

    def __init__(self, *, base_url: str = "http://localhost:11434", model: str = "nomic-embed-text", timeout: float = 5.0):
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.timeout = timeout

    def embed(self, text: str, *, task: TaskType) -> list[float] | None:
        response = httpx.post(
            f"{self.base_url}/api/embed",
            json={"model": self.model, "input": f"{task}: {text}"},
            timeout=self.timeout,
        )
        response.raise_for_status()
        embeddings = response.json().get("embeddings") or []
        if not embeddings:
            raise EmbeddingError("Ollama returned no embeddings")
        return _check_dim(embeddings[0])


class NomicAPIEmbedder:
    """Nomic's managed inference API -- task_type is a request field there,
    not a text prefix."""

    URL = "https://api-atlas.nomic.ai/v1/embedding/text"

    def __init__(self, *, api_key: str, model: str = "nomic-embed-text-v1.5", timeout: float = 5.0):
        self.api_key = api_key
        self.model = model
        self.timeout = timeout

    def embed(self, text: str, *, task: TaskType) -> list[float] | None:
        response = httpx.post(
            self.URL,
            headers={"Authorization": f"Bearer {self.api_key}"},
            json={"model": self.model, "texts": [text], "task_type": task, "dimensionality": EMBEDDING_DIM},
            timeout=self.timeout,
        )
        response.raise_for_status()
        embeddings = response.json().get("embeddings") or []
        if not embeddings:
            raise EmbeddingError("Nomic API returned no embeddings")
        return _check_dim(embeddings[0])


def get_default_embedder() -> Embedder:
    provider = os.environ.get("MEMORY_EMBEDDER", "none").strip().lower()
    if provider == "ollama":
        return OllamaEmbedder(base_url=os.environ.get("OLLAMA_BASE_URL", "http://localhost:11434"))
    if provider == "nomic":
        api_key = os.environ.get("NOMIC_API_KEY")
        if not api_key:
            raise EmbeddingError("MEMORY_EMBEDDER=nomic requires NOMIC_API_KEY")
        return NomicAPIEmbedder(api_key=api_key)
    if provider in ("", "none"):
        return NullEmbedder()
    raise EmbeddingError(f"Unknown MEMORY_EMBEDDER {provider!r} (expected none, ollama, or nomic)")
