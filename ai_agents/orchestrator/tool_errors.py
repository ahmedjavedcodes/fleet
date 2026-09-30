"""Turns an unexpected tool failure into an observation the LLM can explain.

A sub-agent run or a document search can fail in ways its own nodes don't
anticipate: the backend is unreachable, times out, or returns a 5xx (e.g. the
vector index is missing or its provider can't be resolved). Before this, such
an exception escaped execute_tool and ended the whole turn with a generic chat
error. Now it becomes a scratchpad observation, so the turn continues and the
synthesis step can tell the user what isn't available right now.

Only a short, fixed description reaches the LLM (and so the user) -- never a
raw exception message or traceback, which can carry internal hosts, paths or
SQL. The full exception is logged server-side.
"""

from __future__ import annotations

import logging

import httpx

from tools.api_client import BackendAPIError

logger = logging.getLogger("fleet.orchestrator")


def describe_failure(exc: BaseException) -> str:
    if isinstance(exc, BackendAPIError):
        if exc.status_code in (401, 403):
            return f"the backend refused access (HTTP {exc.status_code})"
        if exc.status_code == 404:
            return "the requested record or index was not found (HTTP 404)"
        if exc.status_code >= 500:
            return f"the backend service is temporarily unavailable (HTTP {exc.status_code})"
        return f"the backend rejected the request (HTTP {exc.status_code})"
    if isinstance(exc, httpx.TimeoutException):
        return "the backend did not respond in time"
    if isinstance(exc, httpx.TransportError):
        return "the backend could not be reached"
    return f"an unexpected internal error occurred ({type(exc).__name__})"


def tool_failure_observation(tool_name: str, exc: BaseException) -> str:
    logger.warning("tool %s failed: %s", tool_name, type(exc).__name__, exc_info=exc)
    return (
        f"{tool_name} failed: {describe_failure(exc)}. The step may not have completed. "
        "Do not retry it with the same arguments; tell the user this is unavailable right "
        "now (and, for a change they asked for, that they should check whether it was saved "
        "before trying again), and answer from the other observations if they suffice."
    )
