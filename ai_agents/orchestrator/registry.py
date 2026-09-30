"""Sub-agent registry: the six compiled LangGraphs, exposed uniformly.

Per grand-orchestrator.md FR 1/FR 4/Constraints ("Sub-Agent Immutability"):
none of agents/*/graph.py is modified. Each entry here re-compiles that
agent's existing, unmodified `build_*_graph()` factory with a checkpointer
and `interrupt_before` on its own real mutating nodes -- confirmed by
reading each graph.py's add_node calls, not guessed from the spec's "e.g."
examples (which named only three of the six real node names).

insights has an empty mutating_nodes list: it's read-only (its own spec's
Constraints: "No write operations"), so it never needs a HITL pause.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable

from agents.accountability.graph import AccountabilityAgentDeps, build_accountability_graph
from agents.assignment.graph import AssignmentAgentDeps, build_assignment_graph
from agents.foundation.graph import FoundationAgentDeps, build_foundation_graph
from agents.fuel.graph import FuelAgentDeps, build_fuel_graph
from agents.insights.graph import InsightsAgentDeps, build_insights_graph
from agents.maintenance.graph import MaintenanceAgentDeps, build_maintenance_graph


@dataclass(frozen=True)
class SubAgentSpec:
    name: str
    build_graph: Callable[[Any], Any]  # (deps) -> StateGraph, uncompiled
    deps_factory: Callable[[], Any]  # () -> a fresh *AgentDeps instance
    mutating_nodes: tuple[str, ...]  # real add_node names that write to the backend
    description: str


SUB_AGENT_REGISTRY: dict[str, SubAgentSpec] = {
    "foundation": SubAgentSpec(
        name="foundation",
        build_graph=build_foundation_graph,
        deps_factory=FoundationAgentDeps,
        mutating_nodes=("creating",),
        description=(
            "Fleet Registry Agent: onboard a vehicle (incl. engine_number, chassis_number, "
            "ownership_type), driver (incl. license_type, license_issue_date, "
            "license_current_status), or supplier (incl. address, category) from a "
            "photographed document, or query existing vehicles/drivers/suppliers."
        ),
    ),
    "fuel": SubAgentSpec(
        name="fuel",
        build_graph=build_fuel_graph,
        deps_factory=FuelAgentDeps,
        mutating_nodes=("creating", "creating_trip"),
        description=(
            "Fuel Agent: log a fuel receipt (photo and/or slip details such as slip_id, "
            "po_number, payment_method, card_used, fuel_station_name) or a trip "
            "(driver_id/vehicle_id already resolved), or query fuel logs, trip logs, "
            "fuel trends, or fuel_summary (computed fuel/cost/cost-per-km totals)."
        ),
    ),
    "maintenance": SubAgentSpec(
        name="maintenance",
        build_graph=build_maintenance_graph,
        deps_factory=MaintenanceAgentDeps,
        mutating_nodes=("creating_log", "creating_report", "restocking"),
        description=(
            "Maintenance & Parts Inventory Agent: log a work order/repair (photo or "
            "text; several services per visit, service_scale minor/major, driver who "
            "brought the vehicle in), restock inventory from a parts invoice (photo or text), or query "
            "maintenance/repair history, parts inventory (qty_on_hand, reorder thresholds), low-stock "
            "parts, or which vehicles are due or overdue for service (query_entity=service_due)."
        ),
    ),
    "accountability": SubAgentSpec(
        name="accountability",
        build_graph=build_accountability_graph,
        deps_factory=AccountabilityAgentDeps,
        mutating_nodes=("creating",),
        description=(
            "Driver Accountability Agent: file an incident report (photo or text), "
            "audit trip logs for off-hours activity, or query incidents/driver safety."
        ),
    ),
    "insights": SubAgentSpec(
        name="insights",
        build_graph=build_insights_graph,
        deps_factory=InsightsAgentDeps,
        mutating_nodes=(),  # read-only -- never pauses for approval
        description=(
            "Strategic Insights Agent: executive summary, cross-domain cost "
            "correlation, or query dashboard/fuel-trend/fleet-health data. Read-only."
        ),
    ),
    "assignment": SubAgentSpec(
        name="assignment",
        build_graph=build_assignment_graph,
        deps_factory=AssignmentAgentDeps,
        mutating_nodes=("executing",),
        description=(
            "Assignment Agent: assign a vehicle to a driver, terminate an active "
            "assignment, or query driver/vehicle assignment history."
        ),
    ),
}
