"""HTTP client for calling the FastAPI backend from agent tools.

Per CLAUDE.md's cross-module boundary rule, ai_agents/ never imports backend
code directly -- every read or write an agent performs goes through this
client instead, carrying the caller's own bearer token so the backend's own
auth, RBAC, and org-scoping remain the actual enforcement layer.
"""

from __future__ import annotations

import os
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
    return os.environ.get("BACKEND_API_BASE_URL", "http://localhost:8000")


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

    with httpx.Client(base_url=_base_url(), timeout=timeout) as client:
        response = client.request(method, path, headers=headers, json=json, params=params)

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
