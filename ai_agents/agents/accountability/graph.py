"""Driver Accountability & Asset Misuse Agent orchestration (LangGraph).

Wires the router, extraction, vehicle/driver resolution, the off-hours
trip-audit heuristic, and the MCP tools together per
ai_agents/specs/driver-accountability-agent.md's Behaviour section:

    inject_context -> classify_intent
        -> [incident_onboard] extracting -> resolving_entities -> creating
        -> [trip_audit] auditing
        -> [query] querying

Every dependency is injected via AccountabilityAgentDeps, same pattern as
the other three agents, so tests can substitute fakes without a live
backend or Groq key.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Any, Callable

from langgraph.graph import END, StateGraph

from agents.accountability.misuse_auditor import DEFAULT_END_HOUR, DEFAULT_START_HOUR, audit_trips_for_off_hours
from agents.accountability.state import AccountabilityAgentState
from mcp_server.accountability_tools import (
    PermissionDeniedError,
    create_incident_tool,
    get_driver_timeline_tool,
    get_incidents_tool,
)
from mcp_server.foundation_tools import get_drivers_tool, get_vehicles_tool
from mcp_server.fuel_tools import get_trip_logs_tool
from tools.api_client import BackendAPIError
from tools.auth_context import AgentContext, InvalidTokenError, build_context
from tools.file_parsers import ExtractionFailedError, UnsupportedImageTypeError, extract_incident_report
from tools.sanitize import sanitize_plate_number
from tools.schemas import IncidentCreateInput, IncidentSeverity, IncidentType

Extractor = Callable[..., Any]
Lister = Callable[[AgentContext], list[dict[str, Any]]]


@dataclass
class AccountabilityAgentDeps:
    """Injectable seams. Defaults are the real, backend/Groq-calling tools."""

    extract_incident: Extractor = extract_incident_report
    get_vehicles: Lister = get_vehicles_tool
    get_drivers: Lister = get_drivers_tool
    get_trip_logs: Lister = get_trip_logs_tool
    get_incidents: Lister = get_incidents_tool
    get_driver_timeline: Callable[[AgentContext, str], list[dict[str, Any]]] = get_driver_timeline_tool
    create_incident: Callable[[AgentContext, Any], dict[str, Any]] = create_incident_tool


def _context_from_state(state: AccountabilityAgentState) -> AgentContext:
    return AgentContext(
        token=state.get("token") or "",
        user_id=state.get("user_id") or "",
        organization_id=state.get("organization_id") or "",
        role=state.get("role") or "",
    )


def inject_context(state: AccountabilityAgentState) -> AccountabilityAgentState:
    try:
        context = build_context(state.get("token"))
    except InvalidTokenError as exc:
        return {**state, "stage": "halted", "halt_reason": str(exc)}
    return {
        **state,
        "user_id": context.user_id,
        "organization_id": context.organization_id,
        "role": context.role,
        "stage": "routing",
    }


def classify_intent(state: AccountabilityAgentState) -> AccountabilityAgentState:
    if state.get("document_type") == "incident_report":
        return {**state, "intent": "incident_onboard", "stage": "extracting"}
    if state.get("audit_target") is not None:
        return {**state, "intent": "trip_audit", "stage": "auditing"}
    return {**state, "intent": "query", "stage": "querying"}


def _own_driver_id(context: AgentContext, deps: AccountabilityAgentDeps) -> str | None:
    """Resolves the caller's own Driver.id from their JWT's user_id (a
    User.id) -- these are different primary keys (Driver.id is its own UUID,
    linked to User via Driver.user_id), so this requires a lookup, not a
    direct reuse of context.user_id."""
    return next((d["id"] for d in deps.get_drivers(context) if d.get("user_id") == context.user_id), None)


def _map_severity(raw: str | None) -> IncidentSeverity | None:
    if not raw:
        return None
    try:
        return IncidentSeverity(raw.strip().lower())
    except ValueError:
        return None


def _map_incident_type(raw: str | None) -> IncidentType:
    if raw:
        try:
            return IncidentType(raw.strip().lower())
        except ValueError:
            pass
    return IncidentType.damage


# ---- incident_onboard ----


def _make_extract_node(deps: AccountabilityAgentDeps):
    def extract(state: AccountabilityAgentState) -> AccountabilityAgentState:
        if state.get("extracted") is not None:
            return {**state, "stage": "resolving_entities"}

        image_bytes = state.get("image_bytes")
        text = state.get("document_text")
        try:
            result = deps.extract_incident(image_bytes, state.get("mime_type") or "image/jpeg", text=text)
        except (UnsupportedImageTypeError, ExtractionFailedError, ValueError) as exc:
            return {**state, "stage": "halted", "halt_reason": str(exc)}

        return {**state, "extracted": result.model_dump(), "stage": "resolving_entities"}

    return extract


def _make_resolve_entities_node(deps: AccountabilityAgentDeps):
    def resolve_entities(state: AccountabilityAgentState) -> AccountabilityAgentState:
        extracted = state.get("extracted") or {}
        context = _context_from_state(state)

        plate = sanitize_plate_number(extracted.get("vehicle_plate"))
        if not plate:
            return {**state, "stage": "halted", "halt_reason": "Could not determine the incident's vehicle plate."}

        vehicle = next(
            (v for v in deps.get_vehicles(context) if sanitize_plate_number(v.get("plate_number")) == plate), None
        )
        if vehicle is None:
            return {**state, "stage": "halted", "halt_reason": f"No vehicle on file matches plate {plate!r}."}

        if not (extracted.get("damage_description") or "").strip():
            return {**state, "stage": "halted", "halt_reason": "Could not determine a description of the incident."}

        if _map_severity(extracted.get("severity")) is None:
            return {**state, "stage": "halted", "halt_reason": "Could not determine the incident's severity."}

        # Best-effort: an unmatched driver name doesn't block filing --
        # IncidentLogCreate.driver_id is nullable (an incident can exist
        # with no driver attached).
        resolved_driver_id = None
        driver_name = (extracted.get("driver_name") or "").strip().casefold()
        if driver_name:
            match = next(
                (d for d in deps.get_drivers(context) if (d.get("full_name") or "").strip().casefold() == driver_name),
                None,
            )
            if match is not None:
                resolved_driver_id = match["id"]

        # A driver-role caller can only ever file against their own
        # Driver.id, regardless of what driver_name resolved to (spec's
        # "driver submits for another driver" edge case).
        if context.role == "driver":
            resolved_driver_id = _own_driver_id(context, deps)

        return {**state, "vehicle_id": vehicle["id"], "resolved_driver_id": resolved_driver_id, "stage": "creating"}

    return resolve_entities


def _make_create_node(deps: AccountabilityAgentDeps):
    def create(state: AccountabilityAgentState) -> AccountabilityAgentState:
        context = _context_from_state(state)
        extracted = state.get("extracted") or {}

        data = IncidentCreateInput(
            driver_id=state.get("resolved_driver_id"),
            vehicle_id=state["vehicle_id"],
            incident_type=_map_incident_type(extracted.get("incident_type")),
            date=extracted.get("incident_date") or date.today(),
            severity=_map_severity(extracted.get("severity")),
            description=extracted["damage_description"],
            location_description=extracted.get("location"),
        )

        try:
            record = deps.create_incident(context, data)
        except PermissionDeniedError as exc:
            return {**state, "stage": "halted", "halt_reason": str(exc)}
        except BackendAPIError as exc:
            return {**state, "stage": "halted", "halt_reason": str(exc)}

        return {**state, "created_record": record, "stage": "done"}

    return create


# ---- trip_audit ----


def _make_audit_node(deps: AccountabilityAgentDeps):
    def audit(state: AccountabilityAgentState) -> AccountabilityAgentState:
        context = _context_from_state(state)
        target = state.get("audit_target") or {}

        try:
            trips = deps.get_trip_logs(context)
        except PermissionDeniedError as exc:
            return {**state, "stage": "halted", "halt_reason": str(exc)}

        driver_id = target.get("driver_id")
        vehicle_id = target.get("vehicle_id")
        if driver_id:
            trips = [t for t in trips if t.get("driver_id") == driver_id]
        if vehicle_id:
            trips = [t for t in trips if t.get("vehicle_id") == vehicle_id]

        flagged = audit_trips_for_off_hours(
            trips,
            start_hour=target.get("start_hour", DEFAULT_START_HOUR),
            end_hour=target.get("end_hour", DEFAULT_END_HOUR),
        )
        return {**state, "audit_result": flagged, "stage": "done"}

    return audit


# ---- query ----


def _make_query_node(deps: AccountabilityAgentDeps):
    def query(state: AccountabilityAgentState) -> AccountabilityAgentState:
        entity = state.get("query_entity")
        context = _context_from_state(state)

        try:
            if entity == "incidents":
                result = deps.get_incidents(context)
            elif entity == "driver_safety":
                driver_id = state.get("query_driver_id")
                if not driver_id:
                    return {**state, "stage": "halted", "halt_reason": "driver_safety query requires query_driver_id."}
                timeline = deps.get_driver_timeline(context, driver_id)
                result = _summarize_safety(timeline)
            else:
                return {**state, "stage": "halted", "halt_reason": f"Unsupported or missing query_entity: {entity!r}."}
        except PermissionDeniedError as exc:
            return {**state, "stage": "halted", "halt_reason": str(exc)}
        except BackendAPIError as exc:
            return {**state, "stage": "halted", "halt_reason": str(exc)}

        return {**state, "query_result": result, "stage": "done"}

    return query


def _summarize_safety(timeline: list[dict[str, Any]]) -> dict[str, Any]:
    """Agent-side aggregation over the real /drivers/{id}/timeline endpoint
    -- there is no backend driver-safety-score endpoint (the plan guessed
    at /api/v1/drivers/safety; it doesn't exist)."""
    incidents = [e for e in timeline if e.get("record_type") == "incident"]
    by_severity: dict[str, int] = {}
    for entry in incidents:
        severity = (entry.get("summary") or {}).get("severity", "unknown")
        by_severity[severity] = by_severity.get(severity, 0) + 1
    return {"incident_count": len(incidents), "by_severity": by_severity}


def _route_after(state: AccountabilityAgentState) -> str:
    return "end" if state.get("stage") in ("halted", "done") else state["stage"]


def build_accountability_graph(deps: AccountabilityAgentDeps | None = None) -> StateGraph:
    deps = deps or AccountabilityAgentDeps()
    graph = StateGraph(AccountabilityAgentState)

    graph.add_node("inject_context", inject_context)
    graph.add_node("classify_intent", classify_intent)
    graph.add_node("extracting", _make_extract_node(deps))
    graph.add_node("resolving_entities", _make_resolve_entities_node(deps))
    graph.add_node("creating", _make_create_node(deps))
    graph.add_node("auditing", _make_audit_node(deps))
    graph.add_node("querying", _make_query_node(deps))

    graph.set_entry_point("inject_context")
    graph.add_conditional_edges("inject_context", _route_after, {"end": END, "routing": "classify_intent"})
    graph.add_conditional_edges(
        "classify_intent",
        _route_after,
        {"extracting": "extracting", "auditing": "auditing", "querying": "querying"},
    )
    graph.add_conditional_edges("extracting", _route_after, {"end": END, "resolving_entities": "resolving_entities"})
    graph.add_conditional_edges("resolving_entities", _route_after, {"end": END, "creating": "creating"})
    graph.add_edge("creating", END)
    graph.add_edge("auditing", END)
    graph.add_edge("querying", END)

    return graph


def get_compiled_accountability_graph(deps: AccountabilityAgentDeps | None = None):
    return build_accountability_graph(deps).compile()
