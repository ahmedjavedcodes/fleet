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
from datetime import date, timedelta
from decimal import Decimal, InvalidOperation
from typing import Any, Callable

from langgraph.graph import END, StateGraph
from pydantic import ValidationError

from agents.fuel.efficiency_auditor import OdometerContinuityError, check_odometer_continuity
from agents.fuel.state import FuelAgentState
from agents.fuel.summary import summarize_fuel
from mcp_server.fuel_tools import (
    PermissionDeniedError,
    create_fuel_log_tool,
    create_trip_log_tool,
    get_fuel_logs_tool,
    get_fuel_logs_window_tool,
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
    "date",
    "odometer_reading",
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
    get_fuel_logs_window: Callable[..., tuple[list[dict[str, Any]], bool]] = get_fuel_logs_window_tool
    today: Callable[[], date] = date.today
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
        fields = dict(state["fuel_fields"])
        if not fields.get("date"):
            fields["date"] = date.today().isoformat()  # a typed fill with no date is today's
        if fields.get("odometer_reading") in (None, "") and fields.get("vehicle_id"):
            # Take the vehicle's last recorded reading as the baseline (see validate_odometer) instead of asking.
            return {**state, "intent": "fuel_log", "fuel_fields": fields, "extracted": {}, "stage": "resolving_vehicle"}
        amounts = _resolve_amounts(fields, {})  # two of litres / price / total give the third
        if amounts is not None:
            fields["liters_filled"], fields["price_per_liter"], fields["total_cost"] = amounts
        try:
            FuelLogCreateInput(**fields)
        except (ValidationError, TypeError) as exc:
            return {**state, "intent": "fuel_log", "stage": "halted", "halt_reason": f"Invalid fuel_fields: {exc}"}
        return {**state, "intent": "fuel_log", "sanitized": fields, "stage": "creating"}
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
        stated = (state.get("fuel_fields") or {}).get("vehicle_id")
        context = _context_from_state(state)
        vehicles = deps.get_vehicles(context)

        if stated:
            # The user named the vehicle in chat (the orchestrator resolved it to an id): that wins over a plate
            # read off the photo, which may belong to another vehicle or be misread. A plate in place of an id is
            # accepted too.
            wanted = sanitize_plate_number(str(stated))
            vehicle = next(
                (v for v in vehicles if str(v.get("id")) == str(stated) or sanitize_plate_number(v.get("plate_number")) == wanted),
                None,
            )
            if vehicle is None:
                return {**state, "stage": "halted", "halt_reason": f"No vehicle on file matches {str(stated)!r}."}
        else:
            plate = sanitize_plate_number(extracted.get("plate_number"))
            if not plate:
                return {**state, "stage": "halted", "halt_reason": "Could not determine the receipt's vehicle plate."}
            vehicle = next((v for v in vehicles if sanitize_plate_number(v.get("plate_number")) == plate), None)
            if vehicle is None:
                return {**state, "stage": "halted", "halt_reason": f"No vehicle on file matches plate {plate!r}."}

        return {
            **state,
            "vehicle_id": vehicle["id"],
            "vehicle_plate": vehicle.get("plate_number"),
            "current_odometer": vehicle.get("current_odometer", 0),
            "stage": "sanitizing",
        }

    return resolve_vehicle


def _decimal(value: Any) -> Decimal | None:
    if value in (None, ""):
        return None
    try:
        return Decimal(str(value))
    except InvalidOperation:
        return None


def _resolve_amounts(stated: dict[str, Any], extracted: dict[str, Any]) -> tuple[Decimal, Decimal, Decimal] | None:  # noqa: C901
    """(liters, price_per_liter, total_cost) for the log, or None if they cannot be determined.

    What the user states in chat beats what OCR read off the photo, and the three figures must agree with each
    other: two stated figures fix the third; one stated figure takes the rest from the receipt; none at all is the
    plain receipt (liters and total read, price derived)."""
    liters, price, total = (_decimal(stated.get(key)) for key in ("liters_filled", "price_per_liter", "total_cost"))
    receipt_liters, receipt_total = _decimal(extracted.get("liters")), _decimal(extracted.get("total_cost"))
    given = [v is not None for v in (liters, price, total)].count(True)
    if given == 0:
        liters, total = receipt_liters, receipt_total
        printed = _decimal(extracted.get("price_per_liter"))
        if printed and liters and total and abs(printed * liters - total) <= total * Decimal("0.02"):
            price = printed  # the unit price printed on the slip, when it agrees with litres x price = total
    elif given == 1:
        if liters is not None:
            total = receipt_total
        else:  # only the total or only the price was stated: the litres come from the receipt
            liters = receipt_liters
    if total is None and liters is not None and price is not None:
        total = (liters * price).quantize(Decimal("0.01"))
    if liters is None and price and total is not None:
        liters = (total / price).quantize(Decimal("0.01"))
    if liters is None or liters <= 0 or total is None:
        return None
    if price is None:
        price = total / liters
    return liters, price.quantize(Decimal("0.0001")), total


def sanitize(state: FuelAgentState) -> FuelAgentState:
    extracted = state.get("extracted") or {}
    stated = state.get("fuel_fields") or {}

    amounts = _resolve_amounts(stated, extracted)
    if amounts is None:
        return {
            **state,
            "stage": "halted",
            "halt_reason": "Could not determine the receipt's liters filled and total cost.",
        }
    liters_d, price_per_liter, total_cost_d = amounts

    station_name = extracted.get("station_name")
    payment_method = extracted.get("payment_method")
    bridged = {
        "vehicle_id": state.get("vehicle_id"),
        "date": extracted.get("receipt_date"),
        "odometer_reading": extracted.get("odometer"),
        "liters_filled": liters_d,
        "price_per_liter": price_per_liter,
        "total_cost": total_cost_d,
        "notes": "; ".join(filter(None, [f"Product: {extracted.get('product')}" if extracted.get("product") else None,
                                        f"Station: {station_name}" if station_name else None])) or None,
        "fuel_station_name": station_name or None,
        "slip_id": (extracted.get("slip_id") or "").strip() or None,
        "po_number": (extracted.get("po_number") or "").strip() or None,
        "payment_method": payment_method.strip().lower() if isinstance(payment_method, str) and payment_method.strip() else None,
        "card_used": (extracted.get("card_used") or "").strip() or None,
    }
    # Text supplied alongside (or instead of) the photo wins over what OCR read.
    for key in _SUPPLEMENTARY_FUEL_FIELDS:
        value = stated.get(key)
        if value not in (None, ""):
            bridged[key] = value

    if stated.get("notes"):
        bridged["notes"] = "; ".join(filter(None, [str(stated["notes"]), bridged.get("notes")]))

    # The user's vehicle beat the photo's plate (see resolve_vehicle): leave a trace if they disagree.
    receipt_plate = sanitize_plate_number(extracted.get("plate_number"))
    if receipt_plate and state.get("vehicle_plate") and sanitize_plate_number(state["vehicle_plate"]) != receipt_plate:
        bridged["notes"] = "; ".join(filter(None, [bridged.get("notes"), f"Receipt shows plate {receipt_plate}"]))

    if bridged["date"] is None:
        bridged["date"] = date.today().isoformat()  # an undated receipt is today's fill

    return {**state, "sanitized": bridged, "stage": "validating_odometer"}


def validate_odometer(state: FuelAgentState) -> FuelAgentState:
    sanitized = state.get("sanitized") or {}
    if sanitized.get("odometer_reading") in (None, "") and (state.get("current_odometer") or 0) > 0:
        # Not on the receipt or in the message: the last recorded reading is the baseline, and the log says so.
        note = "odometer not stated: last recorded reading used"
        sanitized = {**sanitized, "odometer_reading": state["current_odometer"], "notes": "; ".join(filter(None, [sanitized.get("notes"), note]))}
        return {**state, "sanitized": sanitized, "stage": "creating"}
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
        except (ValidationError, TypeError) as exc:
            return {**state, "stage": "halted", "halt_reason": f"Invalid fuel_fields: {exc}"}
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


def _fuel_summary(state: FuelAgentState, context: AgentContext, deps: FuelAgentDeps) -> dict[str, Any] | str:
    """Deterministic totals (see agents/fuel/summary.py). Returns the summary, or a halt reason."""
    plate = state.get("query_plate")
    days = state.get("query_days")
    vehicle_id = None
    vehicle_plate = None
    if plate:
        wanted = sanitize_plate_number(plate)
        vehicle = next((v for v in deps.get_vehicles(context) if sanitize_plate_number(v.get("plate_number")) == wanted), None)
        if vehicle is None:
            return f"No vehicle on file matches plate {wanted!r}."
        vehicle_id, vehicle_plate = vehicle["id"], vehicle["plate_number"]

    today = deps.today()
    date_from = (today - timedelta(days=days)).isoformat() if days else None
    rows, complete = deps.get_fuel_logs_window(context, vehicle_id=vehicle_id, date_from=date_from)
    summary = summarize_fuel(rows, plate=vehicle_plate, days=days, today=today)
    summary["complete"] = complete
    if not complete:
        summary["answer_markdown"] += "\n\n_Based on the first 10,000 fuel logs only; older or additional logs were not included._"
    return summary


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
            elif entity == "fuel_summary":
                outcome = _fuel_summary(state, context, deps)
                if isinstance(outcome, str):
                    return {**state, "stage": "halted", "halt_reason": outcome}
                result = outcome
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
            "resolving_vehicle": "resolving_vehicle",
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
