"""Validates a tool call's raw LLM-generated arguments against its
Pydantic schema before any sub-agent ever sees them.

Per grand-orchestrator.md FR 7: protects the sub-agents' extra="forbid"
input assumptions from tool-calling hallucinations (an invented field, a
wrong type, a missing required key). This module only validates and
formats feedback -- it does not itself call the LLM again; the caller
(graph.py's execute_tool node) is responsible for feeding the formatted
observation back to the LLM and re-invoking it, up to MAX_RETRIES times,
consistent with every sub-agent's own dependency-injection pattern (no
hidden retry loop buried in a low-level helper).
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ValidationError

MAX_RETRIES = 2


class ToolValidationError(Exception):
    """Raised when raw tool-call args fail schema validation.

    `observation` is the LLM-facing, human-readable correction message;
    `retries_exhausted` tells the caller whether to hard-fault instead of
    retrying again.
    """

    def __init__(self, observation: str, *, retries_exhausted: bool):
        super().__init__(observation)
        self.observation = observation
        self.retries_exhausted = retries_exhausted


def validate_tool_args(schema: type[BaseModel], raw_args: dict[str, Any], *, attempt: int) -> BaseModel:
    """attempt is 1-indexed (this is the attempt-th call for this tool use).

    Raises ToolValidationError with a formatted field-error summary on
    failure; retries_exhausted is True once `attempt` has reached
    MAX_RETRIES + 1 (i.e. the caller already retried MAX_RETRIES times).
    """
    try:
        return schema.model_validate(raw_args)
    except ValidationError as exc:
        observation = _format_errors(schema, exc)
        return_exhausted = attempt > MAX_RETRIES
        raise ToolValidationError(observation, retries_exhausted=return_exhausted) from exc


def _format_errors(schema: type[BaseModel], exc: ValidationError) -> str:
    allowed_fields = sorted(schema.model_fields.keys())
    lines = [f"Invalid arguments for this tool. Allowed fields: {', '.join(allowed_fields)}."]
    for error in exc.errors():
        field = ".".join(str(p) for p in error["loc"]) or "(root)"
        lines.append(f"- {field}: {error['msg']}")
    return "\n".join(lines)
