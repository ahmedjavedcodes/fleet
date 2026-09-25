"""Driver & Vehicle Assignment Agent orchestration (LangGraph).

Wires the router, vehicle/driver resolution, the conflict guardrail, and
the MCP tools together per ai_agents/specs/assignment-agent.md's Behaviour
section:

    inject_context -> classify_intent
        -> [assign_asset] resolving_entities -> validating_conflicts
           -> executing
        -> [terminate_assignment] resolving_entities -> validating_conflicts
           -> executing
        -> [query] querying

Every dependency is injected via AssignmentAgentDeps, same pattern as the
other five agents, so tests can substitute fakes without a live backend.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable

from langgraph.graph import END, StateGraph

from agents.assignment.conflict_checker import (
    AssignmentConflictError,
    check_driver_available,
    check_vehicle_available,
    check_vehicle_has_active_assignment,
)
from agents.assignment.state import AssignmentAgentState
from mcp_server.assignment_tools import (
    PermissionDeniedError,
    create_assignment_tool,
    get_driver_assignment_history_tool,
    get_vehicle_assignment_history_tool,
    terminate_assignment_tool,
)
from mcp_server.foundation_tools import get_drivers_tool, get_vehicles_tool
from tools.api_client import BackendAPIError
from tools.auth_context import AgentContext, InvalidTokenError, build_context
from tools.sanitize import sanitize_plate_number
from tools.schemas import AssignmentCreateInput, AssignmentTerminateInput

_WRITE_ROLES = frozenset({"admin", "fleet_manager"})

Lister = Callable[[AgentContext], list[dict[str, Any]]]


@dataclass
class AssignmentAgentDeps:
    """Injectable seams. Defaults are the real, backend-calling tools."""

    get_vehicles: Lister = get_vehicles_tool
    get_drivers: Lister = get_drivers_tool
    get_driver_history: Callable[[AgentContext, str], dict[str, Any]] = get_driver_assignment_history_tool
    get_vehicle_history: Callable[..., list[dict[str, Any]]] = get_vehicle_assignment_history_tool
    create_assignment: Callable[[AgentContext, str, Any], dict[str, Any]] = create_assignment_tool
    terminate_assignment: Callable[[AgentContext, str, Any], dict[str, Any]] = terminate_assignment_tool


def _context_from_state(state: AssignmentAgentState) -> AgentContext:
    return AgentContext(
        token=state.get("token") or "",
        user_id=state.get("user_id") or "",
        organization_id=state.get("organization_id") or "",
        role=state.get("role") or "",
    )


def inject_context(state: AssignmentAgentState) -> AssignmentAgentState:
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


def classify_intent(state: AssignmentAgentState) -> AssignmentAgentState:
    is_write = state.get("assign_request") is not None or state.get("terminate_request") is not None

    # Checked here, before resolving_entities makes its first backend call
    # (get_vehicles_tool/get_drivers_tool are ungated reads) -- otherwise a
    # driver/mechanic's write attempt would cost backend round-trips before
    # validating_conflicts' gated history lookup ever caught it, violating
    # the spec's "refuses before making any backend call" (AC 4).
    if is_write and state.get("role") not in _WRITE_ROLES:
        return {
            **state,
            "stage": "halted",
            "halt_reason": f"Role '{state.get('role')}' is not permitted to modify assignments; requires admin/fleet_manager.",
        }

    if state.get("assign_request") is not None:
        return {**state, "intent": "assign_asset", "stage": "resolving_entities"}
    if state.get("terminate_request") is not None:
        return {**state, "intent": "terminate_assignment", "stage": "resolving_entities"}
    return {**state, "intent": "query", "stage": "querying"}


def _resolve_vehicle(deps: AssignmentAgentDeps, context: AgentContext, plate: str | None) -> dict[str, Any] | None:
    plate = sanitize_plate_number(plate)
    if not plate:
        return None
    return next((v for v in deps.get_vehicles(context) if sanitize_plate_number(v.get("plate_number")) == plate), None)


def _resolve_driver(deps: AssignmentAgentDeps, context: AgentContext, name: str | None) -> dict[str, Any] | None:
    needle = (name or "").strip().casefold()
    if not needle:
        return None
    return next((d for d in deps.get_drivers(context) if (d.get("full_name") or "").strip().casefold() == needle), None)


def _make_resolve_entities_node(deps: AssignmentAgentDeps):
    def resolve_entities(state: AssignmentAgentState) -> AssignmentAgentState:
        context = _context_from_state(state)
        intent = state["intent"]
        request = state.get("assign_request") if intent == "assign_asset" else state.get("terminate_request")
        request = request or {}

        vehicle = _resolve_vehicle(deps, context, request.get("vehicle_plate"))
        if vehicle is None:
            return {**state, "stage": "halted", "halt_reason": f"No vehicle on file matches plate {request.get('vehicle_plate')!r}."}

        result: AssignmentAgentState = {**state, "vehicle_id": vehicle["id"], "stage": "validating_conflicts"}

        if intent == "assign_asset":
            driver = _resolve_driver(deps, context, request.get("driver_name"))
            if driver is None:
                return {**state, "stage": "halted", "halt_reason": f"No driver on file matches {request.get('driver_name')!r}."}
            result["driver_id"] = driver["id"]

        return result

    return resolve_entities


def _make_validate_conflicts_node(deps: AssignmentAgentDeps):
    def validate(state: AssignmentAgentState) -> AssignmentAgentState:
        context = _context_from_state(state)

        try:
            vehicle_history = deps.get_vehicle_history(context, state["vehicle_id"])
            if state["intent"] == "assign_asset":
                check_vehicle_available(vehicle_history)
                driver_history = deps.get_driver_history(context, state["driver_id"])
                check_driver_available(driver_history)
            else:
                check_vehicle_has_active_assignment(vehicle_history)
        except AssignmentConflictError as exc:
            return {**state, "stage": "halted", "halt_reason": str(exc)}
        except PermissionDeniedError as exc:
            return {**state, "stage": "halted", "halt_reason": str(exc)}

        return {**state, "stage": "executing"}

    return validate


def _make_execute_node(deps: AssignmentAgentDeps):
    def execute(state: AssignmentAgentState) -> AssignmentAgentState:
        context = _context_from_state(state)

        try:
            if state["intent"] == "assign_asset":
                request = state.get("assign_request") or {}
                data = AssignmentCreateInput(
                    driver_id=state["driver_id"],
                    assigned_at=request["assigned_at"],
                    start_odometer=request["start_odometer"],
                    take_condition=request["take_condition"],
                    take_notes=request.get("take_notes"),
                )
                record = deps.create_assignment(context, state["vehicle_id"], data)
            else:
                request = state.get("terminate_request") or {}
                data = AssignmentTerminateInput(
                    released_at=request["released_at"],
                    end_odometer=request["end_odometer"],
                    leave_condition=request["leave_condition"],
                    leave_notes=request.get("leave_notes"),
                )
                record = deps.terminate_assignment(context, state["vehicle_id"], data)
        except PermissionDeniedError as exc:
            return {**state, "stage": "halted", "halt_reason": str(exc)}
        except BackendAPIError as exc:
            # Race between validating_conflicts and here (409/404) -- report,
            # don't retry, same pattern as the Fleet Registry Agent's
            # duplicate-plate race handling.
            return {**state, "stage": "halted", "halt_reason": str(exc)}

        return {**state, "created_record": record, "stage": "done"}

    return execute


def _make_query_node(deps: AssignmentAgentDeps):
    def query(state: AssignmentAgentState) -> AssignmentAgentState:
        entity = state.get("query_entity")
        context = _context_from_state(state)

        try:
            if entity == "driver_history":
                driver_id = state.get("query_driver_id")
                if not driver_id:
                    return {**state, "stage": "halted", "halt_reason": "driver_history query requires query_driver_id."}
                result = deps.get_driver_history(context, driver_id)
            elif entity == "vehicle_history":
                vehicle_id = state.get("query_vehicle_id")
                if not vehicle_id:
                    return {**state, "stage": "halted", "halt_reason": "vehicle_history query requires query_vehicle_id."}
                result = deps.get_vehicle_history(context, vehicle_id, state.get("query_target_date"))
            else:
                return {**state, "stage": "halted", "halt_reason": f"Unsupported or missing query_entity: {entity!r}."}
        except PermissionDeniedError as exc:
            return {**state, "stage": "halted", "halt_reason": str(exc)}
        except BackendAPIError as exc:
            return {**state, "stage": "halted", "halt_reason": str(exc)}

        return {**state, "query_result": result, "stage": "done"}

    return query


def _route_after(state: AssignmentAgentState) -> str:
    return "end" if state.get("stage") in ("halted", "done") else state["stage"]


def build_assignment_graph(deps: AssignmentAgentDeps | None = None) -> StateGraph:
    deps = deps or AssignmentAgentDeps()
    graph = StateGraph(AssignmentAgentState)

    graph.add_node("inject_context", inject_context)
    graph.add_node("classify_intent", classify_intent)
    graph.add_node("resolving_entities", _make_resolve_entities_node(deps))
    graph.add_node("validating_conflicts", _make_validate_conflicts_node(deps))
    graph.add_node("executing", _make_execute_node(deps))
    graph.add_node("querying", _make_query_node(deps))

    graph.set_entry_point("inject_context")
    graph.add_conditional_edges("inject_context", _route_after, {"end": END, "routing": "classify_intent"})
    graph.add_conditional_edges(
        "classify_intent",
        _route_after,
        {"end": END, "resolving_entities": "resolving_entities", "querying": "querying"},
    )
    graph.add_conditional_edges(
        "resolving_entities", _route_after, {"end": END, "validating_conflicts": "validating_conflicts"}
    )
    graph.add_conditional_edges("validating_conflicts", _route_after, {"end": END, "executing": "executing"})
    graph.add_edge("executing", END)
    graph.add_edge("querying", END)

    return graph


def get_compiled_assignment_graph(deps: AssignmentAgentDeps | None = None):
    return build_assignment_graph(deps).compile()
