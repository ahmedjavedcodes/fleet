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
    context: AgentContext, query: str, document_types: list[str] | None = None, *, timeout: float = 15.0
) -> dict[str, Any]:
    payload: dict[str, Any] = {"query": query}
    if document_types:
        payload["document_types"] = document_types
    return call_backend("POST", "/api/v1/documents/search", token=context.token, json=payload, timeout=timeout)


class BackendDocumentRetriever:
    """What OrchestratorDeps.documents holds in production."""

    def search(self, context: AgentContext, query: str, document_types: list[str] | None = None) -> list[dict]:
        return search_documents_tool(context, query, document_types)["results"]
