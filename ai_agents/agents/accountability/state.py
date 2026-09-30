"""LangGraph state schema for the Driver Accountability & Asset Misuse Agent.

Mirrors ai_agents/specs/driver-accountability-agent.md's Behaviour section:

    Intent: incident_onboard | trip_audit | query
    incident_onboard sub-flow: Extracting -> ResolvingEntities -> Creating
    -> Done | Halted(reason)

Intent is decided structurally, same approach as the other three agents:
document_type == "incident_report" -> incident_onboard; audit_target
present -> trip_audit; neither -> query. No LLM classification call.
"""

from __future__ import annotations

from typing import Any, Literal, TypedDict

Intent = Literal["incident_onboard", "trip_audit", "query"]
DocumentType = Literal["incident_report"]
QueryEntity = Literal["incidents", "driver_safety"]

Stage = Literal[
    "routing",
    "extracting",
    "resolving_entities",
    "creating",
    "auditing",
    "querying",
    "done",
    "halted",
]


class AccountabilityAgentState(TypedDict, total=False):
    # caller context -- token is the raw JWT; the rest are populated by
    # inject_context() from it and re-derived into an AgentContext by any
    # node that needs to call a tool.
    token: str | None
    user_id: str | None
    organization_id: str | None
    role: str | None

    # routing input/output
    intent: Intent | None
    document_type: DocumentType | None
    stage: Stage

    # incident_onboard input (image XOR text)
    image_bytes: bytes | None
    mime_type: str | None
    document_text: str | None
    # Explicit values from the orchestrator's tool call; each wins over what
    # extraction read from the photo/text.
    severity: str | None
    attachment_url: str | None

    # incident_onboard intermediate results
    extracted: dict[str, Any] | None
    vehicle_id: str | None
    resolved_driver_id: str | None
    created_record: dict[str, Any] | None

    # trip_audit input: which driver/vehicle to audit (None = whole org) and
    # an optional [start_hour, end_hour) window override
    audit_target: dict[str, Any] | None
    audit_result: list[dict[str, Any]] | None

    # query input/output -- driver_safety additionally needs query_driver_id
    query_entity: QueryEntity | None
    query_driver_id: str | None
    query_result: Any | None

    # terminal
    halt_reason: str | None
