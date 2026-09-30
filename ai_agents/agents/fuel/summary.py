"""Deterministic fuel aggregation: the arithmetic the LLM must never do itself.

Pure functions, shared by the Fuel agent's `fuel_summary` query (the normal AI path) and the
offline fallback, so both always give the same numbers and the same layout.

Definitions (one place, so they can't drift):
  * litres / cost   -- sums over the fills in the window (Decimal, so no float drift).
  * distance        -- per vehicle, the odometer span between its first and last fill in the
                       window; a fleet total is the sum of those spans. A vehicle with a single
                       fill has no span (needs two readings) and contributes no distance.
  * cost per km     -- total cost / total distance, counting only vehicles that have a distance.
The window's first fill pays for driving that happened before it, so cost per km slightly
overstates; that is the agreed definition, kept simple and reproducible.
"""

from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal, InvalidOperation
from typing import Any

CURRENCY = "Rs"


def _dec(value: Any) -> Decimal | None:
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError):
        return None


def summarize_fuel(
    rows: list[dict[str, Any]], *, plate: str | None = None, days: int | None = None, today: date | None = None
) -> dict[str, Any]:
    """Totals for one vehicle (`plate`) or the whole fleet, over the last `days` days (all rows if None).

    `rows` are backend fuel-log dicts (vehicle_plate, date, liters_filled, total_cost, odometer_reading).
    Filtering by plate/date here is defensive: callers normally fetch a pre-filtered window."""
    today = today or date.today()
    if plate:
        rows = [r for r in rows if str(r.get("vehicle_plate", "")).upper() == plate.upper()]
    if days:
        since = (today - timedelta(days=days)).isoformat()
        rows = [r for r in rows if str(r.get("date", "")) >= since]

    litres = sum((_dec(r.get("liters_filled")) or Decimal(0) for r in rows), Decimal(0))
    cost = sum((_dec(r.get("total_cost")) or Decimal(0) for r in rows), Decimal(0))

    by_vehicle: dict[str, list[Decimal]] = {}
    costs_by_vehicle: dict[str, Decimal] = {}
    for r in rows:
        key = str(r.get("vehicle_plate") or r.get("vehicle_id") or "?")
        costs_by_vehicle[key] = costs_by_vehicle.get(key, Decimal(0)) + (_dec(r.get("total_cost")) or Decimal(0))
        odometer = _dec(r.get("odometer_reading"))
        if odometer is not None:
            by_vehicle.setdefault(key, []).append(odometer)

    distance = Decimal(0)
    cost_with_distance = Decimal(0)
    start = end = None
    for key, readings in by_vehicle.items():
        span = max(readings) - min(readings)
        if len(readings) >= 2 and span > 0:
            distance += span
            cost_with_distance += costs_by_vehicle[key]
            start, end = min(readings), max(readings)

    single_vehicle = len(costs_by_vehicle) == 1
    cost_per_km = (cost_with_distance / distance) if distance > 0 else None
    summary: dict[str, Any] = {
        "vehicle": plate.upper() if plate else None,
        "period_days": days,
        "fills": len(rows),
        "vehicles": len(costs_by_vehicle),
        "liters": float(round(litres, 2)),
        "total_cost": float(round(cost, 2)),
        "distance_km": float(distance) if distance > 0 else None,
        "start_odometer": float(start) if single_vehicle and distance > 0 and start is not None else None,
        "end_odometer": float(end) if single_vehicle and distance > 0 and end is not None else None,
        "cost_per_km": float(round(cost_per_km, 2)) if cost_per_km is not None else None,
        "currency": CURRENCY,
    }
    summary["answer_markdown"] = render_fuel_summary(summary)
    return summary


def _quantity(n: float) -> str:
    return f"{n:,.1f}".rstrip("0").rstrip(".")


def _period(days: int | None) -> str:
    if not days:
        return ""
    return {7: " (Past Week)", 30: " (Past Month)"}.get(days, f" (Past {days} Days)")


def render_fuel_summary(s: dict[str, Any]) -> str:
    subject = f"Vehicle {s['vehicle']}" if s.get("vehicle") else "the Fleet"
    title = f"**Fuel & Cost Summary for {subject}{_period(s.get('period_days'))}**"
    if not s.get("fills"):
        return f"{title}\n* No fuel logs recorded for this period."

    cur = s.get("currency", CURRENCY)
    lines = [
        f"* **Total Fuel Consumed:** {_quantity(s['liters'])} Liters",
        f"* **Total Fuel Cost:** {cur} {s['total_cost']:,.0f}",
    ]
    if s.get("distance_km"):
        span = (
            f" ({s['start_odometer']:,.0f} km → {s['end_odometer']:,.0f} km)"
            if s.get("start_odometer") is not None and s.get("end_odometer") is not None
            else ""
        )
        lines.append(f"* **Total Distance Covered:** {s['distance_km']:,.0f} km{span}")
        lines.append(f"* **Average Cost per km:** {cur} {s['cost_per_km']:,.2f} / km")
    else:
        lines.append("* **Total Distance Covered:** not available (needs at least two fills)")
        lines.append("* **Average Cost per km:** not available")
    return "\n".join([title, *lines])
