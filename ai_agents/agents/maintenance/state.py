"""LangGraph state schema for the Maintenance & Parts Inventory Agent.

Mirrors ai_agents/specs/maintenance-inventory-agent.md's Behaviour section:

    Intent: maintenance_onboard | inventory_restock | query
    maintenance_onboard sub-flow: Extracting -> ResolvingAssets ->
    CreatingLog -> CheckingInventory -> CreatingReport ->
    Done | Halted(reason)

Intent is decided structurally by document_type, same approach as
agents/foundation/router.py and agents/fuel/graph.py's classify_intent:
document_type == "work_order" -> maintenance_onboard; "parts_invoice" ->
inventory_restock; neither -> query. No LLM classification call.
"""

from __future__ import annotations

from typing import Any, Literal, TypedDict

Intent = Literal["maintenance_onboard", "inventory_restock", "query"]
DocumentType = Literal["work_order", "parts_invoice"]
QueryEntity = Literal["maintenance_logs", "inventory", "low_stock", "service_due"]

Stage = Literal[
    "routing",
    "extracting",
    "resolving_assets",
    "creating_log",
    "checking_inventory",
    "creating_report",
    "restocking",
    "querying",
    "done",
    "halted",
]


class MaintenanceAgentState(TypedDict, total=False):
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

    # extraction input (image XOR text)
    image_bytes: bytes | None
    mime_type: str | None
    document_text: str | None

    # maintenance_onboard intermediate results
    extracted: dict[str, Any] | None
    vehicle_id: str | None
    resolved_parts: list[dict[str, Any]]
    resolved_driver_id: str | None
    maintenance_log: dict[str, Any] | None
    mechanic_report: dict[str, Any] | None

    # inventory_restock intermediate results
    updated_parts: list[dict[str, Any]]

    # query input/output
    query_entity: QueryEntity | None
    query_result: Any | None

    # terminal
    halt_reason: str | None
