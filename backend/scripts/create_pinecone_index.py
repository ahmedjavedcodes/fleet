"""One-off, idempotent: create the agent-memory and document-RAG Pinecone indexes.

    python scripts/create_pinecone_index.py

Reads PINECONE_API_KEY / PINECONE_INDEX / PINECONE_CLOUD / PINECONE_REGION from
backend settings (backend/.env). A plain dense index -- embeddings are computed
by ai_agents/ (memory/embeddings.py), so the index stays model-agnostic. Never
touches any other index on the account.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from pinecone import Pinecone, ServerlessSpec  # noqa: E402

from app.core.config import get_settings  # noqa: E402
from app.models.memory import EMBEDDING_DIM  # noqa: E402


def _ensure(pc: Pinecone, name: str, metric: str, purpose: str, settings) -> None:
    if pc.has_index(name):
        print(f"Index {name!r} already exists -- nothing to do.")
        return
    pc.create_index(
        name=name,
        dimension=EMBEDDING_DIM,
        metric=metric,
        spec=ServerlessSpec(cloud=settings.pinecone_cloud, region=settings.pinecone_region),
        tags={"app": "fleet-saas", "purpose": purpose},
    )
    print(f"Created index {name!r} ({EMBEDDING_DIM}-dim, {metric}).")


def main() -> int:
    settings = get_settings()
    if not settings.pinecone_api_key:
        print("PINECONE_API_KEY is not set in backend/.env", file=sys.stderr)
        return 1
    pc = Pinecone(api_key=settings.pinecone_api_key)
    _ensure(pc, settings.pinecone_index, "cosine", "agent-memory", settings)
    # Hybrid dense+sparse queries are only supported on dotproduct indexes.
    _ensure(pc, settings.pinecone_documents_index, "dotproduct", "document-rag", settings)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
