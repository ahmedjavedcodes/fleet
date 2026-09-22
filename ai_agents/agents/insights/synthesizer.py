"""Cross-domain synthesis for the Strategic Insights Agent.

Both functions are pure aggregation over data the backend already computed
or logged -- neither recomputes a health score or invents a statistical
model. per driver-accountability-agent.md's precedent for this codebase:
a heuristic correlation is a review signal, not a verdict.
"""

from __future__ import annotations

from typing import Any

AT_RISK_THRESHOLD = 50


def synthesize_fleet_health(scores: list[dict[str, Any]]) -> dict[str, Any]:
    """scores: mcp_server.insights_tools.get_fleet_health_tool's response
    (a list of {vehicle_id, plate_number, health_score, signals}).

    Handles the empty-fleet case gracefully (edge case: "backend endpoint
    returns empty data... report zero-state counters without crashing").
    """
    if not scores:
        return {"average_health_score": None, "vehicle_count": 0, "at_risk_count": 0, "vehicles": []}

    values = [s["health_score"] for s in scores]
    at_risk = [s for s in scores if s["health_score"] < AT_RISK_THRESHOLD]

    return {
        "average_health_score": round(sum(values) / len(values), 1),
        "vehicle_count": len(scores),
        "at_risk_count": len(at_risk),
        "vehicles": scores,
    }


def correlate_costs(fuel_by_vehicle: list[dict[str, Any]], maintenance_logs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """fuel_by_vehicle: get_fuel_summary_tool's response["by_vehicle"]
    (each {vehicle_id, total_cost, ...}).
    maintenance_logs: get_maintenance_logs_tool's response (each has
    vehicle_id and a nullable cost).

    Returns one row per vehicle appearing in either source, sorted
    descending by combined cost -- the highest-cost vehicles surface first
    as capital-drain/retirement candidates for a human to review.
    """
    maintenance_cost_by_vehicle: dict[str, float] = {}
    for log in maintenance_logs:
        vehicle_id = log.get("vehicle_id")
        if vehicle_id is None:
            continue
        maintenance_cost_by_vehicle[vehicle_id] = maintenance_cost_by_vehicle.get(vehicle_id, 0.0) + float(
            log.get("cost") or 0
        )

    fuel_cost_by_vehicle = {f["vehicle_id"]: float(f.get("total_cost") or 0) for f in fuel_by_vehicle}

    vehicle_ids = set(maintenance_cost_by_vehicle) | set(fuel_cost_by_vehicle)
    correlated = [
        {
            "vehicle_id": vehicle_id,
            "fuel_cost": fuel_cost_by_vehicle.get(vehicle_id, 0.0),
            "maintenance_cost": maintenance_cost_by_vehicle.get(vehicle_id, 0.0),
            "total_cost": fuel_cost_by_vehicle.get(vehicle_id, 0.0) + maintenance_cost_by_vehicle.get(vehicle_id, 0.0),
        }
        for vehicle_id in vehicle_ids
    ]
    correlated.sort(key=lambda row: row["total_cost"], reverse=True)
    return correlated
