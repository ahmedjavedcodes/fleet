"""Fleet Registry Agent orchestration (LangGraph).

Wires the router, vision extraction skills, sanitization, validation
sub-agents, and MCP tools together per
ai_agents/specs/fleet-registry-agent.md's Behaviour section:

    inject_context -> classify_intent -> [onboard] extract -> sanitize
        -> validate_expiry (license only) -> validate_duplicate -> create
                                            -> [query] query

Every dependency (vision extractors, get_*_tool/create_*_tool) is injected
via FoundationAgentDeps rather than imported and called directly inside
node closures, so tests can substitute fakes without a live backend, Groq
key, or JWT signer.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable

from langgraph.graph import END, StateGraph

from agents.foundation.duplicate_checker import (
    find_duplicate_driver,
    find_duplicate_supplier,
    find_duplicate_vehicle,
)
from agents.foundation.license_inspector import ExpiredLicenseError, inspect_license
from agents.foundation.state import FoundationAgentState
from mcp_server.foundation_tools import (
    PermissionDeniedError,
    create_driver_tool,
    create_supplier_tool,
    create_vehicle_tool,
    get_drivers_tool,
    get_suppliers_tool,
    get_vehicles_tool,
)
from tools.api_client import BackendAPIError
from tools.auth_context import AgentContext, InvalidTokenError, build_context
from tools.file_parsers import (
    ExtractionFailedError,
    UnsupportedImageTypeError,
    extract_license_data,
    extract_supplier_doc,
    extract_vehicle_doc,
)
from tools.sanitize import (
    sanitize_license_number,
    sanitize_name,
    sanitize_phone,
    sanitize_plate_number,
    sanitize_vin,
)
from tools.schemas import DriverCreateInput, LicenseExtraction, SupplierCreateInput, VehicleCreateInput

Extractor = Callable[[bytes, str], Any]
Lister = Callable[[AgentContext], list[dict[str, Any]]]
Creator = Callable[[AgentContext, Any], dict[str, Any]]


@dataclass
class FoundationAgentDeps:
    """Injectable seams. Defaults are the real, backend/Groq-calling tools."""

    extract_license: Extractor = extract_license_data
    extract_vehicle: Extractor = extract_vehicle_doc
    extract_supplier: Extractor = extract_supplier_doc
    get_vehicles: Lister = get_vehicles_tool
    get_drivers: Lister = get_drivers_tool
    get_suppliers: Lister = get_suppliers_tool
    create_vehicle: Creator = create_vehicle_tool
    create_driver: Creator = create_driver_tool
    create_supplier: Creator = create_supplier_tool


_REQUIRED_FIELDS = {
    "license": ["full_name", "license_number", "license_expiry", "phone"],
    "vehicle_doc": ["plate_number", "make", "model", "year", "vin", "fuel_type"],
    "supplier_doc": ["name"],
}


def _context_from_state(state: FoundationAgentState) -> AgentContext:
    return AgentContext(
        token=state.get("token") or "",
        user_id=state.get("user_id") or "",
        organization_id=state.get("organization_id") or "",
        role=state.get("role") or "",
    )


def inject_context(state: FoundationAgentState) -> FoundationAgentState:
    """Reads the caller's JWT and extracts organization_id/role (spec: "Agent
    Router & Context Injector" box) -- the backend still independently
    verifies the token's signature and permissions on every call it receives.
    """
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


def classify_intent(state: FoundationAgentState) -> FoundationAgentState:
    intent = "onboard" if state.get("image_bytes") else "query"
    stage = "extracting" if intent == "onboard" else "querying"
    return {**state, "intent": intent, "stage": stage}


def _make_extract_node(deps: FoundationAgentDeps):
    extractors: dict[str, Extractor] = {
        "license": deps.extract_license,
        "vehicle_doc": deps.extract_vehicle,
        "supplier_doc": deps.extract_supplier,
    }

    def extract(state: FoundationAgentState) -> FoundationAgentState:
        # Idempotent: a resumed invocation (after awaiting_missing_field)
        # already has `extracted` populated and skips straight to sanitize.
        if state.get("extracted") is not None:
            return {**state, "stage": "sanitizing"}

        document_type = state.get("document_type")
        image_bytes = state.get("image_bytes")
        mime_type = state.get("mime_type") or "image/jpeg"
        extractor = extractors.get(document_type or "")

        if extractor is None or image_bytes is None:
            return {**state, "stage": "halted", "halt_reason": f"Unsupported or missing document_type: {document_type!r}."}

        try:
            result = extractor(image_bytes, mime_type)
        except (UnsupportedImageTypeError, ExtractionFailedError) as exc:
            return {**state, "stage": "halted", "halt_reason": str(exc)}

        return {**state, "extracted": result.model_dump(), "stage": "sanitizing"}

    return extract


def sanitize(state: FoundationAgentState) -> FoundationAgentState:
    document_type = state["document_type"]
    extracted = state.get("extracted") or {}
    provided = state.get("provided_fields") or {}

    if document_type == "license":
        full_name = sanitize_name(f"{extracted.get('first_name') or ''} {extracted.get('last_name') or ''}".strip())
        bridged: dict[str, Any] = {
            "full_name": full_name or None,
            "license_number": sanitize_license_number(extracted.get("license_number")) or None,
            "license_expiry": extracted.get("expiration_date"),
            "phone": sanitize_phone(extracted.get("phone_number")) or None,
        }
    elif document_type == "vehicle_doc":
        bridged = {
            "plate_number": sanitize_plate_number(extracted.get("plate_number")) or None,
            "make": extracted.get("make"),
            "model": extracted.get("model"),
            "year": extracted.get("year"),
            "vin": sanitize_vin(extracted.get("vin")) or None,
            "current_odometer": extracted.get("initial_odometer") or 0,
            "fuel_type": provided.get("fuel_type"),
        }
    else:  # supplier_doc
        bridged = {
            "name": sanitize_name(extracted.get("name")) or None,
            "contact_email": (extracted.get("contact_email") or "").strip().lower() or None,
            "phone": sanitize_phone(extracted.get("phone")) or None,
        }

    required = _REQUIRED_FIELDS[document_type]
    missing = [f for f in required if not bridged.get(f)]

    if missing:
        return {**state, "sanitized": bridged, "missing_fields": missing, "stage": "awaiting_missing_field"}

    next_stage = "validating_expiry" if document_type == "license" else "validating_duplicate"
    return {**state, "sanitized": bridged, "missing_fields": [], "stage": next_stage}


def validate_expiry(state: FoundationAgentState) -> FoundationAgentState:
    sanitized = state.get("sanitized") or {}
    try:
        inspect_license(LicenseExtraction(expiration_date=sanitized.get("license_expiry")))
    except ExpiredLicenseError as exc:
        return {**state, "stage": "halted", "halt_reason": str(exc)}
    return {**state, "stage": "validating_duplicate"}


def _make_validate_duplicate_node(deps: FoundationAgentDeps):
    def validate_duplicate(state: FoundationAgentState) -> FoundationAgentState:
        context = _context_from_state(state)
        sanitized = state.get("sanitized") or {}
        document_type = state["document_type"]

        duplicate = _find_duplicate(deps, context, document_type, sanitized)
        if duplicate is not None:
            return {
                **state,
                "duplicate_of": duplicate,
                "stage": "halted",
                "halt_reason": "A matching record already exists.",
            }
        return {**state, "stage": "creating"}

    return validate_duplicate


def _find_duplicate(
    deps: FoundationAgentDeps, context: AgentContext, document_type: str, sanitized: dict[str, Any]
) -> dict[str, Any] | None:
    if document_type == "license":
        return find_duplicate_driver(context, sanitized.get("license_number") or "", get_drivers=deps.get_drivers)
    if document_type == "vehicle_doc":
        return find_duplicate_vehicle(context, sanitized.get("plate_number") or "", get_vehicles=deps.get_vehicles)
    return find_duplicate_supplier(context, sanitized.get("name") or "", get_suppliers=deps.get_suppliers)


def _make_create_node(deps: FoundationAgentDeps):
    def create(state: FoundationAgentState) -> FoundationAgentState:
        context = _context_from_state(state)
        document_type = state["document_type"]
        sanitized = state.get("sanitized") or {}

        try:
            if document_type == "license":
                record = deps.create_driver(context, DriverCreateInput(**sanitized))
            elif document_type == "vehicle_doc":
                record = deps.create_vehicle(context, VehicleCreateInput(**sanitized))
            else:
                record = deps.create_supplier(context, SupplierCreateInput(**sanitized))
        except PermissionDeniedError as exc:
            return {**state, "stage": "halted", "halt_reason": str(exc)}
        except BackendAPIError as exc:
            if exc.status_code == 409:
                # Race window between the pre-check and this call (AC 4):
                # re-check once to surface the conflicting record, no retry.
                duplicate = _find_duplicate(deps, context, document_type, sanitized)
                return {
                    **state,
                    "duplicate_of": duplicate,
                    "stage": "halted",
                    "halt_reason": "A matching record was created concurrently.",
                }
            return {**state, "stage": "halted", "halt_reason": str(exc)}

        return {**state, "created_record": record, "stage": "done"}

    return create


def _make_query_node(deps: FoundationAgentDeps):
    listers: dict[str, Lister] = {
        "vehicles": deps.get_vehicles,
        "drivers": deps.get_drivers,
        "suppliers": deps.get_suppliers,
    }

    def query(state: FoundationAgentState) -> FoundationAgentState:
        entity = state.get("query_entity")
        lister = listers.get(entity or "")
        if lister is None:
            return {**state, "stage": "halted", "halt_reason": f"Unsupported or missing query_entity: {entity!r}."}

        context = _context_from_state(state)
        return {**state, "query_result": lister(context), "stage": "done"}

    return query


def _route_after(state: FoundationAgentState) -> str:
    """Generic post-node router: END on any terminal stage, else the stage name doubles as the next node name."""
    return "end" if state.get("stage") in ("halted", "done", "awaiting_missing_field") else state["stage"]


def build_foundation_graph(deps: FoundationAgentDeps | None = None) -> StateGraph:
    deps = deps or FoundationAgentDeps()
    graph = StateGraph(FoundationAgentState)

    graph.add_node("inject_context", inject_context)
    graph.add_node("classify_intent", classify_intent)
    graph.add_node("extracting", _make_extract_node(deps))
    graph.add_node("sanitizing", sanitize)
    graph.add_node("validating_expiry", validate_expiry)
    graph.add_node("validating_duplicate", _make_validate_duplicate_node(deps))
    graph.add_node("creating", _make_create_node(deps))
    graph.add_node("querying", _make_query_node(deps))

    graph.set_entry_point("inject_context")
    graph.add_conditional_edges("inject_context", _route_after, {"end": END, "routing": "classify_intent"})
    graph.add_conditional_edges(
        "classify_intent", _route_after, {"extracting": "extracting", "querying": "querying"}
    )
    graph.add_conditional_edges("extracting", _route_after, {"end": END, "sanitizing": "sanitizing"})
    graph.add_conditional_edges(
        "sanitizing",
        _route_after,
        {"end": END, "validating_expiry": "validating_expiry", "validating_duplicate": "validating_duplicate"},
    )
    graph.add_conditional_edges(
        "validating_expiry", _route_after, {"end": END, "validating_duplicate": "validating_duplicate"}
    )
    graph.add_conditional_edges("validating_duplicate", _route_after, {"end": END, "creating": "creating"})
    graph.add_edge("creating", END)
    graph.add_edge("querying", END)

    return graph


def get_compiled_foundation_graph(deps: FoundationAgentDeps | None = None):
    return build_foundation_graph(deps).compile()
