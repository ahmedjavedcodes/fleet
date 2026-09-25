"""Pydantic schemas for orchestrator telemetry, per fleet-live-observer.md §3.

These validate a trace immediately before it's queued. Instantiating either
model is the last line of defense: `input_payload`/`observation` must
already have been through `redact.redact_payload` by the time they get
here (FR 5 / AC 1) -- the schema does not redact for you.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

ToolStatus = Literal["done", "halted", "awaiting_approval", "schema_error"]


def _now() -> datetime:
    return datetime.now(timezone.utc)


class LLMTrace(BaseModel):
    model_config = ConfigDict(extra="forbid")

    trace_id: str
    organization_id: str
    user_id: str
    model_name: str
    prompt_tokens: int
    completion_tokens: int
    latency_ms: int
    timestamp: datetime = Field(default_factory=_now)


class ToolTrace(BaseModel):
    model_config = ConfigDict(extra="forbid")

    trace_id: str
    organization_id: str
    user_id: str
    agent_name: str
    # FR 8 (retry transparency): a schema_error trace and its corrected
    # successor share a trace_id and differ by attempt, so billing can sum
    # every attempt while dashboards filter to the final outcome.
    attempt: int
    input_payload: dict[str, Any]  # redacted before instantiation
    status: ToolStatus
    observation: str  # redacted before instantiation
    latency_ms: int
    timestamp: datetime = Field(default_factory=_now)
