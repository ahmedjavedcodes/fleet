"""Fuel Vision & Leakage Auditor Agent orchestration (LangGraph).

Wires the router, vision extraction, vehicle resolution, the odometer
continuity guardrail, and the MCP tools together per
ai_agents/specs/fuel-agent.md's Behaviour section:

    inject_context -> classify_intent
        -> [receipt_onboard] extracting -> resolving_vehicle -> sanitizing
           -> validating_odometer -> creating
        -> [trip_log] creating_trip
        -> [query] querying

Every dependency (vision extractor, get_*_tool/create_*_tool) is injected
via FuelAgentDeps rather than imported and called directly inside node
closures, so tests can substitute fakes without a live backend or Groq key
-- same pattern as agents/foundation/graph.py's FoundationAgentDeps.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Any, Callable

from langgraph.graph import END, StateGraph
from pydantic import ValidationError

from agents.fuel.efficiency_auditor import OdometerContinuityError, check_odometer_continuity
from agents.fuel.state import FuelAgentState
from mcp_server.fuel_tools import (
    PermissionDeniedError,
    create_fuel_log_tool,
    create_trip_log_tool,
    get_fuel_logs_tool,
    get_fuel_trends_tool,
    get_trip_logs_tool,
)
from mcp_server.foundation_tools import get_vehicles_tool
from tools.api_client import BackendAPIError
from tools.auth_context import AgentContext, InvalidTokenError, build_context
from tools.file_parsers import ExtractionFailedError, UnsupportedImageTypeError, extract_fuel_receipt
from tools.sanitize import sanitize_plate_number
from tools.schemas import FuelLogCreateInput, TripLogCreateInput

# Slip/receipt attributes a caller can supply in chat (fuel_fields) to complete or
# correct a receipt log -- e.g. "slip 8841, PO 1207, paid with the fleet card".
_SUPPLEMENTARY_FUEL_FIELDS = (
    "slip_id",
    "po_number",
    "payment_method",
    "card_used",
    "fuel_station_name",
    "driver_id",
    "notes",
)

Extractor = Callable[[bytes, str], Any]
Lister = Callable[[AgentContext], list[dict[str, Any]]]
Creator = Callable[[AgentContext, Any], dict[str, Any]]


@dataclass
class FuelAgentDeps:
    """Injectable seams. Defaults are the real, backend/Groq-calling tools."""

    extract_receipt: Extractor = extract_fuel_receipt
    get_vehicles: Lister = get_vehicles_tool
    get_fuel_logs: Lister = get_fuel_logs_tool
    get_trip_logs: Lister = get_trip_logs_tool
    get_fuel_trends: Callable[[AgentContext], dict[str, Any]] = get_fuel_trends_tool
    create_fuel_log: Creator = create_fuel_log_tool
    create_trip_log: Creator = create_trip_log_tool


def _context_from_state(state: FuelAgentState) -> AgentContext:
    return AgentContext(
        token=state.get("token") or "",
        user_id=state.get("user_id") or "",
        organization_id=state.get("organization_id") or "",
        role=state.get("role") or "",
    )


def inject_context(state: FuelAgentState) -> FuelAgentState:
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


def classify_intent(state: FuelAgentState) -> FuelAgentState:
    if state.get("image_bytes"):
        return {**state, "intent": "receipt_onboard", "stage": "extracting"}
    trip_fields = state.get("trip_fields")
    if trip_fields is not None:
        # Same up-front check as fuel_fields: a bad key or a negative
        # fuel_consumed halts with a readable reason, not a traceback.
        try:
            TripLogCreateInput(**trip_fields)
        except (ValidationError, TypeError) as exc:
            return {**state, "intent": "trip_log", "stage": "halted", "halt_reason": f"Invalid trip_fields: {exc}"}
        return {**state, "intent": "trip_log", "stage": "creating_trip"}
    if state.get("fuel_fields") is not None:
        # Text-only fuel log (no receipt photo): every FuelLogCreateInput field must
        # already be in fuel_fields. Validate up front so a missing/extra key halts
        # with a readable reason instead of a traceback at the create node.
        try:
            FuelLogCreateInput(**state["fuel_fields"])
        except (ValidationError, TypeError) as exc:
            return {**state, "intent": "fuel_log", "stage": "halted", "halt_reason": f"Invalid fuel_fields: {exc}"}
        return {**state, "intent": "fuel_log", "sanitized": dict(state["fuel_fields"]), "stage": "creating"}
    return {**state, "intent": "query", "stage": "querying"}


def _make_extract_node(deps: FuelAgentDeps):
    def extract(state: FuelAgentState) -> FuelAgentState:
        if state.get("extracted") is not None:
            return {**state, "stage": "resolving_vehicle"}

        image_bytes = state.get("image_bytes")
        mime_type = state.get("mime_type") or "image/jpeg"
        if image_bytes is None:
            return {**state, "stage": "halted", "halt_reason": "No receipt image was provided."}

        try:
            result = deps.extract_receipt(image_bytes, mime_type)
        except (UnsupportedImageTypeError, ExtractionFailedError) as exc:
            return {**state, "stage": "halted", "halt_reason": str(exc)}

        return {**state, "extracted": result.model_dump(), "stage": "resolving_vehicle"}

    return extract


def _make_resolve_vehicle_node(deps: FuelAgentDeps):
    def resolve_vehicle(state: FuelAgentState) -> FuelAgentState:
        extracted = state.get("extracted") or {}
        plate = sanitize_plate_number(extracted.get("plate_number"))
        if not plate:
            return {**state, "stage": "halted", "halt_reason": "Could not determine the receipt's vehicle plate."}

        context = _context_from_state(state)
        vehicle = next(
            (v for v in deps.get_vehicles(context) if sanitize_plate_number(v.get("plate_number")) == plate),
            None,
        )
        if vehicle is None:
            return {**state, "stage": "halted", "halt_reason": f"No vehicle on file matches plate {plate!r}."}

        return {
            **state,
            "vehicle_id": vehicle["id"],
            "current_odometer": vehicle.get("current_odometer", 0),
            "stage": "sanitizing",
        }

    return resolve_vehicle


def sanitize(state: FuelAgentState) -> FuelAgentState:
    extracted = state.get("extracted") or {}
    liters = extracted.get("liters")
    total_cost = extracted.get("total_cost")

    if not liters or liters <= 0 or total_cost is None:
        return {
            **state,
            "stage": "halted",
            "halt_reason": "Could not determine the receipt's liters filled and total cost.",
        }

    try:
        liters_d = Decimal(str(liters))
        total_cost_d = Decimal(str(total_cost))
        price_per_liter = (total_cost_d / liters_d).quantize(Decimal("0.0001"))
    except (InvalidOperation, ZeroDivisionError):
        return {**state, "stage": "halted", "halt_reason": "Could not compute price per liter from the receipt."}

    station_name = extracted.get("station_name")
    payment_method = extracted.get("payment_method")
    bridged = {
        "vehicle_id": state.get("vehicle_id"),
        "date": extracted.get("receipt_date"),
        "odometer_reading": extracted.get("odometer"),
        "liters_filled": liters_d,
        "price_per_liter": price_per_liter,
        "total_cost": total_cost_d,
        "notes": f"Station: {station_name}" if station_name else None,
        "fuel_station_name": station_name or None,
        "slip_id": (extracted.get("slip_id") or "").strip() or None,
        "po_number": (extracted.get("po_number") or "").strip() or None,
        "payment_method": payment_method.strip().lower() if isinstance(payment_method, str) and payment_method.strip() else None,
        "card_used": (extracted.get("card_used") or "").strip() or None,
    }
    # Text supplied alongside (or instead of) the photo wins over what OCR read.
    for key in _SUPPLEMENTARY_FUEL_FIELDS:
        value = (state.get("fuel_fields") or {}).get(key)
        if value not in (None, ""):
            bridged[key] = value

    if bridged["date"] is None:
        return {**state, "stage": "halted", "halt_reason": "Could not determine the receipt's date."}

    return {**state, "sanitized": bridged, "stage": "validating_odometer"}


def validate_odometer(state: FuelAgentState) -> FuelAgentState:
    sanitized = state.get("sanitized") or {}
    try:
        check_odometer_continuity(sanitized.get("odometer_reading"), state.get("current_odometer") or 0)
    except OdometerContinuityError as exc:
        return {**state, "stage": "halted", "halt_reason": str(exc)}
    return {**state, "stage": "creating"}


def _make_create_fuel_node(deps: FuelAgentDeps):
    def create(state: FuelAgentState) -> FuelAgentState:
        context = _context_from_state(state)
        sanitized = state.get("sanitized") or {}
        try:
            record = deps.create_fuel_log(context, FuelLogCreateInput(**sanitized))
        except PermissionDeniedError as exc:
            return {**state, "stage": "halted", "halt_reason": str(exc)}
        except BackendAPIError as exc:
            return {**state, "stage": "halted", "halt_reason": str(exc)}
        return {**state, "created_record": record, "stage": "done"}

    return create


def _make_create_trip_node(deps: FuelAgentDeps):
    def create_trip(state: FuelAgentState) -> FuelAgentState:
        context = _context_from_state(state)
        trip_fields = state.get("trip_fields") or {}
        try:
            record = deps.create_trip_log(context, TripLogCreateInput(**trip_fields))
        except PermissionDeniedError as exc:
            return {**state, "stage": "halted", "halt_reason": str(exc)}
        except BackendAPIError as exc:
            return {**state, "stage": "halted", "halt_reason": str(exc)}
        return {**state, "created_record": record, "stage": "done"}

    return create_trip


def _make_query_node(deps: FuelAgentDeps):
    def query(state: FuelAgentState) -> FuelAgentState:
        entity = state.get("query_entity")
        context = _context_from_state(state)

        try:
            if entity == "fuel_logs":
                result = deps.get_fuel_logs(context)
            elif entity == "trip_logs":
                result = deps.get_trip_logs(context)
            elif entity == "fuel_trends":
                result = deps.get_fuel_trends(context)
            else:
                return {**state, "stage": "halted", "halt_reason": f"Unsupported or missing query_entity: {entity!r}."}
        except PermissionDeniedError as exc:
            return {**state, "stage": "halted", "halt_reason": str(exc)}

        return {**state, "query_result": result, "stage": "done"}

    return query


def _route_after(state: FuelAgentState) -> str:
    return "end" if state.get("stage") in ("halted", "done") else state["stage"]


def build_fuel_graph(deps: FuelAgentDeps | None = None) -> StateGraph:
    deps = deps or FuelAgentDeps()
    graph = StateGraph(FuelAgentState)

    graph.add_node("inject_context", inject_context)
    graph.add_node("classify_intent", classify_intent)
    graph.add_node("extracting", _make_extract_node(deps))
    graph.add_node("resolving_vehicle", _make_resolve_vehicle_node(deps))
    graph.add_node("sanitizing", sanitize)
    graph.add_node("validating_odometer", validate_odometer)
    graph.add_node("creating", _make_create_fuel_node(deps))
    graph.add_node("creating_trip", _make_create_trip_node(deps))
    graph.add_node("querying", _make_query_node(deps))

    graph.set_entry_point("inject_context")
    graph.add_conditional_edges("inject_context", _route_after, {"end": END, "routing": "classify_intent"})
    graph.add_conditional_edges(
        "classify_intent",
        _route_after,
        {
            "end": END,
            "extracting": "extracting",
            "creating": "creating",
            "creating_trip": "creating_trip",
            "querying": "querying",
        },
    )
    graph.add_conditional_edges("extracting", _route_after, {"end": END, "resolving_vehicle": "resolving_vehicle"})
    graph.add_conditional_edges("resolving_vehicle", _route_after, {"end": END, "sanitizing": "sanitizing"})
    graph.add_conditional_edges(
        "sanitizing", _route_after, {"end": END, "validating_odometer": "validating_odometer"}
    )
    graph.add_conditional_edges("validating_odometer", _route_after, {"end": END, "creating": "creating"})
    graph.add_edge("creating", END)
    graph.add_edge("creating_trip", END)
    graph.add_edge("querying", END)

    return graph


def get_compiled_fuel_graph(deps: FuelAgentDeps | None = None):
    return build_fuel_graph(deps).compile()
