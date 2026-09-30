"""HTTP client for calling the FastAPI backend from agent tools.

Per CLAUDE.md's cross-module boundary rule, ai_agents/ never imports backend
code directly -- every read or write an agent performs goes through this
client instead, carrying the caller's own bearer token so the backend's own
auth, RBAC, and org-scoping remain the actual enforcement layer.
"""

from __future__ import annotations

import os
import threading
from typing import Any

import httpx


class BackendAPIError(Exception):
    """Raised when the backend returns a non-2xx response.

    Preserves the backend's own error detail (e.g. a 409 duplicate-plate
    conflict or a 403 RBAC rejection) so callers can react to it directly
    instead of re-deriving what went wrong from a generic HTTP exception.
    """

    def __init__(self, status_code: int, detail: Any):
        self.status_code = status_code
        self.detail = detail
        super().__init__(f"Backend returned {status_code}: {detail}")


def _base_url() -> str:
    # 127.0.0.1, not "localhost": on Windows "localhost" resolves to ::1 first,
    # and uvicorn's 0.0.0.0 bind is IPv4-only, so every call stalled ~2s on the
    # IPv6 attempt before falling back (measured) -- enough to blow the memory
    # fetch budget on every turn.
    return os.environ.get("BACKEND_API_BASE_URL", "http://127.0.0.1:8000")


_client: httpx.Client | None = None
_client_lock = threading.Lock()


def _http_client() -> httpx.Client:
    """One pooled client for the whole process. Constructing an httpx.Client
    loads the SSL trust store, which measured 0.4-2s on the Windows dev box --
    paid on EVERY backend call when each call built its own client, versus
    ~6ms for a request on a reused one. httpx.Client is safe to share across
    threads (its connection pool is lock-protected)."""
    global _client
    if _client is None:
        with _client_lock:
            if _client is None:
                _client = httpx.Client()
    return _client


def call_backend(
    method: str,
    path: str,
    *,
    token: str | None = None,
    json: dict[str, Any] | None = None,
    params: dict[str, Any] | None = None,
    timeout: float = 10.0,
) -> Any:
    """Call the backend REST API and return the parsed JSON body.

    Raises BackendAPIError on any non-2xx response.
    """
    headers = {"Authorization": f"Bearer {token}"} if token else {}

    response = _http_client().request(
        method, f"{_base_url()}{path}", headers=headers, json=json, params=params, timeout=timeout
    )

    if response.status_code >= 400:
        try:
            body = response.json()
            detail = body.get("detail", body) if isinstance(body, dict) else body
        except ValueError:
            detail = response.text
        raise BackendAPIError(response.status_code, detail)

    if response.status_code == 204 or not response.content:
        return None
    return response.json()
