"""Backend wrapper for document RAG search (/api/v1/documents/search).

No client-side RBAC: which document types a role may see is decided by the
backend from the verified JWT (hybrid-document-rag-pipeline.md §1.1) -- the
agent layer only ever sees what the caller is allowed to see.
"""

from __future__ import annotations

from typing import Any

from tools.api_client import call_backend
from tools.auth_context import AgentContext


def search_documents_tool(
    context: AgentContext,
    query: str,
    document_types: list[str] | None = None,
    *,
    document_ids: list[str] | None = None,
    timeout: float = 15.0,
) -> dict[str, Any]:
    """document_ids restricts the search to exactly those documents (the user's "@" mentions); the backend also
    enforces it, so it can only narrow what the caller may see."""
    payload: dict[str, Any] = {"query": query}
    if document_types:
        payload["document_types"] = document_types
    if document_ids:
        payload["document_ids"] = document_ids
    return call_backend("POST", "/api/v1/documents/search", token=context.token, json=payload, timeout=timeout)


def get_document_tool(context: AgentContext, document_id: str) -> dict[str, Any]:
    """One document's record, under the caller's own visibility (another organization's or a role-restricted one is a 404)."""
    return call_backend("GET", f"/api/v1/documents/{document_id}", token=context.token)


def get_document_chunks_tool(context: AgentContext, document_id: str) -> list[dict[str, Any]]:
    """A document's stored passages in reading order (empty until it is ready), under the caller's own visibility."""
    return call_backend("GET", f"/api/v1/documents/{document_id}/chunks", token=context.token)


def spread(items: list[Any], count: int) -> list[Any]:
    """`count` items spread evenly over the list, always including the first and the last."""
    if len(items) <= count:
        return list(items)
    if count <= 1:
        return items[:1]
    indexes = sorted({round(i * (len(items) - 1) / (count - 1)) for i in range(count)})
    return [items[i] for i in indexes]


class BackendDocumentRetriever:
    """What OrchestratorDeps.documents holds in production."""

    OVERVIEW_PASSAGES = 8  # per document: about 2,500 characters, enough for a summary

    def overview(self, context: AgentContext, document_ids: list[str]) -> list[dict]:
        """Passages spread over the whole of each named document, for "summarize this" -- a request that matches no
        particular passage, so a relevance search would find none. Shaped like search results."""
        results: list[dict] = []
        for document_id in document_ids:
            document = get_document_tool(context, document_id)
            chunks = get_document_chunks_tool(context, document_id)
            for chunk in spread(chunks, self.OVERVIEW_PASSAGES):
                results.append({
                    "document_id": document_id,
                    "filename": document.get("filename", ""),
                    "document_type": document.get("document_type", ""),
                    "chunk_index": chunk["chunk_index"],
                    "text": chunk["text"],
                    "relevance": 1.0,
                })
        return results

    def search(
        self, context: AgentContext, query: str, document_types: list[str] | None = None, *, document_ids: list[str] | None = None
    ) -> list[dict]:
        return search_documents_tool(context, query, document_types, document_ids=document_ids)["results"]
