"""Pinecone vector memory for FleetCopilot long-term recall.

Stores embeddings of mechanic notes, driver reports, and incident logs so
the agent can match new issues against historical breakdown patterns.
"""

from __future__ import annotations

import os
from typing import Any


def get_pinecone_index():
    from pinecone import Pinecone

    pc = Pinecone(api_key=os.environ["PINECONE_API_KEY"])
    return pc.Index(os.environ.get("PINECONE_INDEX", "fleet-memory"))


def upsert_memory(index, *, record_id: str, embedding: list[float], metadata: dict[str, Any]) -> None:
    index.upsert(vectors=[{"id": record_id, "values": embedding, "metadata": metadata}])


def query_memory(
    index,
    *,
    embedding: list[float],
    top_k: int = 5,
    filter: dict[str, Any] | None = None,
):
    return index.query(vector=embedding, top_k=top_k, filter=filter, include_metadata=True)
