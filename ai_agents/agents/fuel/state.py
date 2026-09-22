"""LangGraph state schema for the Fuel Vision & Leakage Auditor Agent.

Mirrors ai_agents/specs/fuel-agent.md's Behaviour section:

    Intent: receipt_onboard | trip_log | query
    receipt_onboard sub-flow: Extracting -> ResolvingVehicle -> Sanitizing
    -> ValidatingOdometer -> Creating -> Done | Halted(reason)

Intent is decided structurally, same approach as
agents/foundation/router.py: image_bytes present -> receipt_onboard;
trip_fields present -> trip_log; otherwise -> query. No LLM classification
call -- the caller already knows which of the three it's doing by which
fields it populates.
"""

from __future__ import annotations

from typing import Any, Literal, TypedDict

Intent = Literal["receipt_onboard", "trip_log", "query"]
QueryEntity = Literal["fuel_logs", "trip_logs", "fuel_trends"]

Stage = Literal[
    "routing",
    "extracting",
    "resolving_vehicle",
    "sanitizing",
    "validating_odometer",
    "creating",
    "creating_trip",
    "querying",
    "done",
    "halted",
]


class FuelAgentState(TypedDict, total=False):
    # caller context -- token is the raw JWT; the rest are populated by
    # inject_context() from it and re-derived into an AgentContext by any
    # node that needs to call a tool.
    token: str | None
    user_id: str | None
    organization_id: str | None
    role: str | None

    # routing input/output
    intent: Intent | None
    stage: Stage

    # receipt_onboard input
    image_bytes: bytes | None
    mime_type: str | None

    # receipt_onboard intermediate results
    extracted: dict[str, Any] | None
    vehicle_id: str | None
    current_odometer: int | None
    sanitized: dict[str, Any] | None
    created_record: dict[str, Any] | None

    # trip_log input -- presence of this key (even empty) signals intent
    trip_fields: dict[str, Any] | None

    # query input/output
    query_entity: QueryEntity | None
    query_result: Any | None

    # terminal
    halt_reason: str | None
