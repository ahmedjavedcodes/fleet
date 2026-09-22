"""Pydantic tool-call schemas the routing LLM must fill in exactly.

Per grand-orchestrator.md FR 3 ("Structural Intent Forcing"): each schema's
fields ARE the structural keys the matching sub-agent's classify_intent
reads directly (e.g. AssignmentToolInput.assign_request populates
AssignmentAgentState.assign_request verbatim) -- one schema per sub-agent,
covering the union of all of that agent's intents, since which fields end
up non-null is exactly how the sub-agent's own router decides intent. No
separate LLM-side intent classification exists; this *is* the zero-shot
routing FR 3 asks for.

extra="forbid" on every model is what FR 7's retry wrapper (retry.py)
actually protects against -- a hallucinated extra field raises
pydantic.ValidationError here before the sub-agent ever sees it.

image_bytes/mime_type are deliberately NOT fields on any of these models:
an LLM cannot usefully generate raw image bytes as a tool-call argument.
When the user's turn has an attachment, the orchestrator runtime (session.py)
supplies image_bytes/mime_type itself, out-of-band, onto whichever
sub-agent state the LLM's document_type selects.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict


class FoundationToolInput(BaseModel):
    """Fleet Registry Agent. Set document_type when the user attached a photo
    this turn (license/vehicle_doc/supplier_doc); set provided_fields to
    answer a prior awaiting_missing_field prompt (e.g. {"fuel_type": "diesel"});
    set query_entity for a read."""

    model_config = ConfigDict(extra="forbid")

    document_type: Literal["license", "vehicle_doc", "supplier_doc"] | None = None
    provided_fields: dict[str, Any] | None = None
    query_entity: Literal["vehicles", "drivers", "suppliers"] | None = None


class FuelToolInput(BaseModel):
    """Fuel Agent. Set document_type="receipt" when the user attached a fuel
    receipt photo this turn. Set trip_fields to log a trip -- vehicle_id and
    driver_id must already be resolved UUIDs (query first if you only have a
    plate/name). Set query_entity for a read."""

    model_config = ConfigDict(extra="forbid")

    document_type: Literal["receipt"] | None = None
    trip_fields: dict[str, Any] | None = None
    query_entity: Literal["fuel_logs", "trip_logs", "fuel_trends"] | None = None


class MaintenanceToolInput(BaseModel):
    """Maintenance & Parts Inventory Agent. Set document_type
    ("work_order"/"parts_invoice") when the user attached a photo this turn,
    or set document_text to the typed note/invoice text instead. Set
    query_entity for a read."""

    model_config = ConfigDict(extra="forbid")

    document_type: Literal["work_order", "parts_invoice"] | None = None
    document_text: str | None = None
    query_entity: Literal["maintenance_logs", "inventory", "low_stock"] | None = None


class AccountabilityToolInput(BaseModel):
    """Driver Accountability Agent. Set document_type="incident_report" when
    the user attached a photo this turn, or document_text for a typed
    statement. Set audit_target ({"driver_id"|"vehicle_id": ..., "start_hour":
    ..., "end_hour": ...}) to run the off-hours trip audit. Set query_entity
    (+ query_driver_id for driver_safety) for a read."""

    model_config = ConfigDict(extra="forbid")

    document_type: Literal["incident_report"] | None = None
    document_text: str | None = None
    audit_target: dict[str, Any] | None = None
    query_entity: Literal["incidents", "driver_safety"] | None = None
    query_driver_id: str | None = None


class InsightsToolInput(BaseModel):
    """Strategic Insights Agent (read-only, admin/fleet_manager only). Set
    request_type for an executive summary or cross-domain cost analysis,
    or query_entity for a single-metric read."""

    model_config = ConfigDict(extra="forbid")

    request_type: Literal["executive_summary", "cost_analysis"] | None = None
    month: str | None = None
    query_entity: Literal["dashboard_summary", "fuel_trends", "fleet_health"] | None = None


class AssignmentToolInput(BaseModel):
    """Assignment Agent. Set assign_request ({"vehicle_plate", "driver_name",
    "assigned_at", "start_odometer", "take_condition", "take_notes"}) to pair
    a vehicle and driver. Set terminate_request ({"vehicle_plate",
    "released_at", "end_odometer", "leave_condition", "leave_notes"}) to
    release one. Set query_entity (+ query_driver_id/query_vehicle_id) for a
    read."""

    model_config = ConfigDict(extra="forbid")

    assign_request: dict[str, Any] | None = None
    terminate_request: dict[str, Any] | None = None
    query_entity: Literal["driver_history", "vehicle_history"] | None = None
    query_driver_id: str | None = None
    query_vehicle_id: str | None = None
    query_target_date: str | None = None


TOOL_SCHEMAS: dict[str, type[BaseModel]] = {
    "foundation": FoundationToolInput,
    "fuel": FuelToolInput,
    "maintenance": MaintenanceToolInput,
    "accountability": AccountabilityToolInput,
    "insights": InsightsToolInput,
    "assignment": AssignmentToolInput,
}
