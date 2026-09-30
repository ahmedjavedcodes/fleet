"""Maintenance & Parts Inventory Agent orchestration (LangGraph).

Wires the router, extraction, vehicle/part resolution, the stock-check
guardrail, and the MCP tools together per
ai_agents/specs/maintenance-inventory-agent.md's Behaviour section:

    inject_context -> classify_intent
        -> [maintenance_onboard] extracting -> resolving_assets
           -> creating_log -> checking_inventory -> creating_report
        -> [inventory_restock] extracting_invoice -> resolving_invoice_parts
           -> restocking
        -> [query] querying

Maintenance logging is genuinely a two-backend-call flow (FR 4): the log is
created first, then the mechanic report (which is where parts actually get
consumed) second. Anything that fails from checking_inventory onward means
the MaintenanceLog already exists -- every halt from that point names it,
per the spec's Constraints on partial completion.

Every dependency is injected via MaintenanceAgentDeps, same pattern as
FoundationAgentDeps/FuelAgentDeps, so tests can substitute fakes without a
live backend or Groq key.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Any, Callable

from langgraph.graph import END, StateGraph

from agents.maintenance.state import MaintenanceAgentState
from agents.maintenance.stock_checker import StockDeficitError, check_stock_sufficient
from mcp_server.foundation_tools import get_drivers_tool, get_vehicles_tool
from mcp_server.maintenance_tools import (
    PermissionDeniedError,
    create_maintenance_log_tool,
    create_mechanic_report_tool,
    get_inventory_tool,
    get_low_stock_tool,
    get_maintenance_logs_tool,
    get_service_due_tool,
    update_inventory_tool,
)
from tools.api_client import BackendAPIError
from tools.auth_context import AgentContext, InvalidTokenError, build_context
from tools.file_parsers import (
    ExtractionFailedError,
    UnsupportedImageTypeError,
    extract_parts_invoice,
    extract_work_order,
)
from tools.sanitize import sanitize_plate_number
from tools.schemas import (
    InventoryUpdateInput,
    MaintenanceLogCreateInput,
    MechanicReportCreateInput,
    ResolvedPartUsed,
    ServiceScale,
    ServiceType,
)

Extractor = Callable[..., Any]
Lister = Callable[[AgentContext], list[dict[str, Any]]]


@dataclass
class MaintenanceAgentDeps:
    """Injectable seams. Defaults are the real, backend/Groq-calling tools."""

    extract_work_order: Extractor = extract_work_order
    extract_parts_invoice: Extractor = extract_parts_invoice
    get_vehicles: Lister = get_vehicles_tool
    get_drivers: Lister = get_drivers_tool
    get_inventory: Lister = get_inventory_tool
    get_low_stock: Lister = get_low_stock_tool
    get_maintenance_logs: Lister = get_maintenance_logs_tool
    get_service_due: Callable[[AgentContext], dict[str, Any]] = get_service_due_tool
    create_maintenance_log: Callable[[AgentContext, Any], dict[str, Any]] = create_maintenance_log_tool
    create_mechanic_report: Callable[[AgentContext, str, Any], dict[str, Any]] = create_mechanic_report_tool
    update_inventory: Callable[[AgentContext, str, Any], dict[str, Any]] = update_inventory_tool


def _context_from_state(state: MaintenanceAgentState) -> AgentContext:
    return AgentContext(
        token=state.get("token") or "",
        user_id=state.get("user_id") or "",
        organization_id=state.get("organization_id") or "",
        role=state.get("role") or "",
    )


def inject_context(state: MaintenanceAgentState) -> MaintenanceAgentState:
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


def classify_intent(state: MaintenanceAgentState) -> MaintenanceAgentState:
    document_type = state.get("document_type")
    if document_type == "work_order":
        return {**state, "intent": "maintenance_onboard", "stage": "extracting"}
    if document_type == "parts_invoice":
        return {**state, "intent": "inventory_restock", "stage": "extracting_invoice"}
    return {**state, "intent": "query", "stage": "querying"}


def _resolve_part(name_or_sku: str, inventory: list[dict[str, Any]]) -> dict[str, Any] | None:
    needle = (name_or_sku or "").strip().casefold()
    if not needle:
        return None
    for part in inventory:
        if (part.get("part_number") or "").strip().casefold() == needle:
            return part
    for part in inventory:
        if (part.get("name") or "").strip().casefold() == needle:
            return part
    return None


def _map_service_types(extracted: dict[str, Any]) -> list[ServiceType]:
    """Every service on the work order, de-duplicated in order. Falls back to the
    single (legacy) service_type, then to [other], so a work order that lists no
    recognisable service still files rather than failing on an optional detail."""
    raw_items = list(extracted.get("service_types") or [])
    if extracted.get("service_type"):
        raw_items.append(extracted["service_type"])
    mapped: list[ServiceType] = []
    for raw in raw_items:
        try:
            service = ServiceType(str(raw).strip().lower().replace(" ", "_"))
        except ValueError:
            continue
        if service not in mapped:
            mapped.append(service)
    return mapped or [ServiceType.other]


def _map_service_scale(raw: str | None) -> ServiceScale:
    if raw:
        try:
            return ServiceScale(raw.strip().lower())
        except ValueError:
            pass
    return ServiceScale.minor


# ---- maintenance_onboard ----


def _make_extract_work_order_node(deps: MaintenanceAgentDeps):
    def extract(state: MaintenanceAgentState) -> MaintenanceAgentState:
        if state.get("extracted") is not None:
            return {**state, "stage": "resolving_assets"}

        image_bytes = state.get("image_bytes")
        text = state.get("document_text")
        try:
            result = deps.extract_work_order(image_bytes, state.get("mime_type") or "image/jpeg", text=text)
        except (UnsupportedImageTypeError, ExtractionFailedError, ValueError) as exc:
            return {**state, "stage": "halted", "halt_reason": str(exc)}

        return {**state, "extracted": result.model_dump(), "stage": "resolving_assets"}

    return extract


def _make_resolve_assets_node(deps: MaintenanceAgentDeps):
    def resolve_assets(state: MaintenanceAgentState) -> MaintenanceAgentState:
        extracted = state.get("extracted") or {}
        context = _context_from_state(state)

        plate = sanitize_plate_number(extracted.get("vehicle_plate"))
        if not plate:
            return {**state, "stage": "halted", "halt_reason": "Could not determine the work order's vehicle plate."}

        vehicle = next(
            (v for v in deps.get_vehicles(context) if sanitize_plate_number(v.get("plate_number")) == plate), None
        )
        if vehicle is None:
            return {**state, "stage": "halted", "halt_reason": f"No vehicle on file matches plate {plate!r}."}

        if not extracted.get("odometer"):
            return {**state, "stage": "halted", "halt_reason": "Could not determine the work order's odometer reading."}

        # Best-effort: an unmatched driver name doesn't block filing -- driver_id is optional.
        resolved_driver_id = None
        driver_name = (extracted.get("driver_name") or "").strip().casefold()
        if driver_name:
            driver = next(
                (d for d in deps.get_drivers(context) if (d.get("full_name") or "").strip().casefold() == driver_name),
                None,
            )
            if driver is not None:
                resolved_driver_id = driver["id"]

        inventory = deps.get_inventory(context)
        resolved_parts: list[dict[str, Any]] = []
        for item in extracted.get("parts_used") or []:
            name_or_sku = item.get("name_or_sku")
            qty = item.get("qty")
            part = _resolve_part(name_or_sku, inventory)
            if part is None or not qty:
                return {
                    **state,
                    "stage": "halted",
                    "halt_reason": f"No inventory part matches {name_or_sku!r}.",
                }
            resolved_parts.append({"part_id": part["id"], "qty": qty})

        return {
            **state,
            "vehicle_id": vehicle["id"],
            "resolved_parts": resolved_parts,
            "resolved_driver_id": resolved_driver_id,
            "stage": "creating_log",
        }

    return resolve_assets


def _make_create_log_node(deps: MaintenanceAgentDeps):
    def create_log(state: MaintenanceAgentState) -> MaintenanceAgentState:
        context = _context_from_state(state)
        extracted = state.get("extracted") or {}

        description = extracted.get("issue_description")
        labor_hours = extracted.get("labor_hours")
        if labor_hours:
            description = f"{description or ''} (labor: {labor_hours}h)".strip()

        data = MaintenanceLogCreateInput(
            vehicle_id=state["vehicle_id"],
            date=date.today(),
            odometer_at_service=extracted.get("odometer"),
            service_types=_map_service_types(extracted),
            service_scale=_map_service_scale(extracted.get("service_scale")),
            driver_id=state.get("resolved_driver_id"),
            description=description or None,
            cost=extracted.get("cost"),
        )

        try:
            record = deps.create_maintenance_log(context, data)
        except PermissionDeniedError as exc:
            return {**state, "stage": "halted", "halt_reason": str(exc)}
        except BackendAPIError as exc:
            return {**state, "stage": "halted", "halt_reason": str(exc)}

        return {**state, "maintenance_log": record, "stage": "checking_inventory"}

    return create_log


def _make_check_inventory_node(deps: MaintenanceAgentDeps):
    def check_inventory(state: MaintenanceAgentState) -> MaintenanceAgentState:
        context = _context_from_state(state)
        resolved_parts = state.get("resolved_parts") or []

        if not resolved_parts:
            return {**state, "stage": "creating_report"}

        inventory = deps.get_inventory(context)
        try:
            check_stock_sufficient(resolved_parts, inventory)
        except StockDeficitError as exc:
            log_id = (state.get("maintenance_log") or {}).get("id")
            return {
                **state,
                "stage": "halted",
                "halt_reason": f"{exc} (maintenance log {log_id} was already created; no parts were recorded.)",
            }

        return {**state, "stage": "creating_report"}

    return check_inventory


def _make_create_report_node(deps: MaintenanceAgentDeps):
    def create_report(state: MaintenanceAgentState) -> MaintenanceAgentState:
        context = _context_from_state(state)
        extracted = state.get("extracted") or {}
        log_id = (state.get("maintenance_log") or {}).get("id")

        data = MechanicReportCreateInput(
            diagnostic_notes=extracted.get("issue_description"),
            parts_used=[ResolvedPartUsed(**p) for p in state.get("resolved_parts") or []],
        )

        try:
            record = deps.create_mechanic_report(context, log_id, data)
        except PermissionDeniedError as exc:
            return {**state, "stage": "halted", "halt_reason": str(exc)}
        except BackendAPIError as exc:
            if exc.status_code == 400:
                return {
                    **state,
                    "stage": "halted",
                    "halt_reason": (
                        f"A matching insufficient-stock conflict occurred: {exc.detail}. "
                        f"Maintenance log {log_id} was already created; no parts were recorded."
                    ),
                }
            return {**state, "stage": "halted", "halt_reason": str(exc)}

        return {**state, "mechanic_report": record, "stage": "done"}

    return create_report


# ---- inventory_restock ----


def _make_extract_invoice_node(deps: MaintenanceAgentDeps):
    def extract(state: MaintenanceAgentState) -> MaintenanceAgentState:
        if state.get("extracted") is not None:
            return {**state, "stage": "resolving_invoice_parts"}

        image_bytes = state.get("image_bytes")
        text = state.get("document_text")
        try:
            result = deps.extract_parts_invoice(image_bytes, state.get("mime_type") or "image/jpeg", text=text)
        except (UnsupportedImageTypeError, ExtractionFailedError, ValueError) as exc:
            return {**state, "stage": "halted", "halt_reason": str(exc)}

        return {**state, "extracted": result.model_dump(), "stage": "resolving_invoice_parts"}

    return extract


def _make_resolve_invoice_node(deps: MaintenanceAgentDeps):
    def resolve_invoice(state: MaintenanceAgentState) -> MaintenanceAgentState:
        extracted = state.get("extracted") or {}
        context = _context_from_state(state)
        inventory = deps.get_inventory(context)

        resolved: list[dict[str, Any]] = []
        for item in extracted.get("line_items") or []:
            identifier = item.get("part_number") or item.get("name")
            qty_received = item.get("qty_received")
            part = _resolve_part(identifier, inventory)
            if part is None or not qty_received:
                return {**state, "stage": "halted", "halt_reason": f"No inventory part matches {identifier!r}."}
            resolved.append({"part_id": part["id"], "new_qty": part["qty_on_hand"] + qty_received})

        if not resolved:
            return {**state, "stage": "halted", "halt_reason": "No usable line items were extracted from the invoice."}

        return {**state, "resolved_parts": resolved, "stage": "restocking"}

    return resolve_invoice


def _make_restock_node(deps: MaintenanceAgentDeps):
    def restock(state: MaintenanceAgentState) -> MaintenanceAgentState:
        context = _context_from_state(state)
        updated: list[dict[str, Any]] = []

        for item in state.get("resolved_parts") or []:
            try:
                record = deps.update_inventory(context, item["part_id"], InventoryUpdateInput(qty_on_hand=item["new_qty"]))
            except PermissionDeniedError as exc:
                return {**state, "updated_parts": updated, "stage": "halted", "halt_reason": str(exc)}
            except BackendAPIError as exc:
                return {**state, "updated_parts": updated, "stage": "halted", "halt_reason": str(exc)}
            updated.append(record)

        return {**state, "updated_parts": updated, "stage": "done"}

    return restock


# ---- query ----


def _make_query_node(deps: MaintenanceAgentDeps):
    # Readers return a list, except service_due ({"overdue": [...], "upcoming": [...]}).
    listers: dict[str, Callable[[AgentContext], Any]] = {
        "maintenance_logs": deps.get_maintenance_logs,
        "inventory": deps.get_inventory,
        "low_stock": deps.get_low_stock,
        "service_due": deps.get_service_due,
    }

    def query(state: MaintenanceAgentState) -> MaintenanceAgentState:
        entity = state.get("query_entity")
        lister = listers.get(entity or "")
        if lister is None:
            return {**state, "stage": "halted", "halt_reason": f"Unsupported or missing query_entity: {entity!r}."}

        context = _context_from_state(state)
        try:
            result = lister(context)
        except (PermissionDeniedError, BackendAPIError) as exc:
            return {**state, "stage": "halted", "halt_reason": str(exc)}

        return {**state, "query_result": result, "stage": "done"}

    return query


def _route_after(state: MaintenanceAgentState) -> str:
    return "end" if state.get("stage") in ("halted", "done") else state["stage"]


def build_maintenance_graph(deps: MaintenanceAgentDeps | None = None) -> StateGraph:
    deps = deps or MaintenanceAgentDeps()
    graph = StateGraph(MaintenanceAgentState)

    graph.add_node("inject_context", inject_context)
    graph.add_node("classify_intent", classify_intent)
    graph.add_node("extracting", _make_extract_work_order_node(deps))
    graph.add_node("resolving_assets", _make_resolve_assets_node(deps))
    graph.add_node("creating_log", _make_create_log_node(deps))
    graph.add_node("checking_inventory", _make_check_inventory_node(deps))
    graph.add_node("creating_report", _make_create_report_node(deps))
    graph.add_node("extracting_invoice", _make_extract_invoice_node(deps))
    graph.add_node("resolving_invoice_parts", _make_resolve_invoice_node(deps))
    graph.add_node("restocking", _make_restock_node(deps))
    graph.add_node("querying", _make_query_node(deps))

    graph.set_entry_point("inject_context")
    graph.add_conditional_edges("inject_context", _route_after, {"end": END, "routing": "classify_intent"})
    graph.add_conditional_edges(
        "classify_intent",
        _route_after,
        {"extracting": "extracting", "extracting_invoice": "extracting_invoice", "querying": "querying"},
    )
    graph.add_conditional_edges("extracting", _route_after, {"end": END, "resolving_assets": "resolving_assets"})
    graph.add_conditional_edges("resolving_assets", _route_after, {"end": END, "creating_log": "creating_log"})
    graph.add_conditional_edges("creating_log", _route_after, {"end": END, "checking_inventory": "checking_inventory"})
    graph.add_conditional_edges(
        "checking_inventory", _route_after, {"end": END, "creating_report": "creating_report"}
    )
    graph.add_edge("creating_report", END)

    graph.add_conditional_edges(
        "extracting_invoice", _route_after, {"end": END, "resolving_invoice_parts": "resolving_invoice_parts"}
    )
    graph.add_conditional_edges(
        "resolving_invoice_parts", _route_after, {"end": END, "restocking": "restocking"}
    )
    graph.add_edge("restocking", END)

    graph.add_edge("querying", END)

    return graph


def get_compiled_maintenance_graph(deps: MaintenanceAgentDeps | None = None):
    return build_maintenance_graph(deps).compile()
