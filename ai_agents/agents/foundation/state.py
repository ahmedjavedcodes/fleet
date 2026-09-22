"""LangGraph state schema for the Fleet Registry Agent.

Mirrors ai_agents/specs/fleet-registry-agent.md's Behaviour section:

    Intent: Onboard | Query
    Onboarding sub-flow: Extracting -> Sanitizing -> ValidatingExpiry
    (drivers only) -> ValidatingDuplicate -> AwaitingMissingField
    (conditional) -> Creating -> Done | Halted(reason)
"""

from __future__ import annotations

from typing import Any, Literal, TypedDict

Intent = Literal["onboard", "query"]
DocumentType = Literal["license", "vehicle_doc", "supplier_doc"]
QueryEntity = Literal["vehicles", "drivers", "suppliers"]

Stage = Literal[
    "routing",
    "extracting",
    "sanitizing",
    "validating_expiry",
    "validating_duplicate",
    "awaiting_missing_field",
    "creating",
    "querying",
    "done",
    "halted",
]


class FoundationAgentState(TypedDict, total=False):
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

    # onboarding input
    document_type: DocumentType | None
    image_bytes: bytes | None
    mime_type: str | None
    # fields the caller supplies in-chat to fill an extraction gap (e.g.
    # {"fuel_type": "diesel"}), merged in on a follow-up graph invocation --
    # see the "awaiting_missing_field" stage.
    provided_fields: dict[str, Any]

    # onboarding intermediate results
    extracted: dict[str, Any] | None
    sanitized: dict[str, Any] | None
    missing_fields: list[str]
    duplicate_of: dict[str, Any] | None
    created_record: dict[str, Any] | None

    # query input/output
    query_entity: QueryEntity | None
    query_result: list[dict[str, Any]] | None

    # terminal
    halt_reason: str | None
