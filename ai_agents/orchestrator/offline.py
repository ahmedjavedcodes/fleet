"""Last-resort answers when EVERY language model is unavailable.

A plain read ("which vehicles are due for service?", "fuel used by CD-5678 last month") does
not need an LLM to be answered: it needs the right sub-agent query and a formatter. This maps
a read-only question to one deterministic sub-agent query (through the normal runner, so RBAC,
org scoping and the backend's own checks all still apply) and renders the result as a short,
readable Markdown summary -- computed figures where people ask for them (fuel totals), one
readable line per record otherwise. Never raw field names, never a stringified dict.

It never writes: only query_entity reads are issued, and only for turns the read classifier
accepts. If no rule matches it returns None and the caller shows the original error.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Any, Callable

from orchestrator.turn_profile import classify_turn

_PLATE = re.compile(r"\b([A-Z]{2,3}-\d{3,4})\b")
MAX_ROWS = 8
CURRENCY = "Rs"
FOOTNOTE = "_The AI assistant is unavailable, so this was compiled directly from the fleet records._"


@dataclass(frozen=True)
class OfflineRead:
    agent: str
    args: dict[str, Any]
    label: str


# (pattern, read) -- first match wins, so specific rules come first.
_RULES: list[tuple[re.Pattern[str], OfflineRead]] = [
    (re.compile(r"\b(due|overdue|upcoming)\b.*\bservic|\bservic\w*\b.*\b(due|overdue)\b", re.I), OfflineRead("maintenance", {"query_entity": "service_due"}, "service due")),
    (re.compile(r"\blow[- ]stock|reorder", re.I), OfflineRead("maintenance", {"query_entity": "low_stock"}, "low-stock parts")),
    (re.compile(r"\b(parts?|inventory|spares?|stock)\b", re.I), OfflineRead("maintenance", {"query_entity": "inventory"}, "parts inventory")),
    (re.compile(r"\b(maintenance|repairs?)\b", re.I), OfflineRead("maintenance", {"query_entity": "maintenance_logs"}, "maintenance history")),
    (re.compile(r"\b(trips?|odometer|mileage)\b", re.I), OfflineRead("fuel", {"query_entity": "trip_logs"}, "trips")),
    (re.compile(r"\bfuel|refill|litres?|liters?|cost per k", re.I), OfflineRead("fuel", {"query_entity": "fuel_logs"}, "fuel logs")),
    (re.compile(r"\b(incidents?|accidents?|damage|violations?)\b", re.I), OfflineRead("accountability", {"query_entity": "incidents"}, "incidents")),
    (re.compile(r"\bhealth\b", re.I), OfflineRead("insights", {"query_entity": "fleet_health"}, "fleet health")),
    (re.compile(r"\b(dashboard|summary|overview)\b", re.I), OfflineRead("insights", {"query_entity": "dashboard_summary"}, "dashboard summary")),
    (re.compile(r"\bdrivers?\b", re.I), OfflineRead("foundation", {"query_entity": "drivers"}, "drivers")),
    (re.compile(r"\bsuppliers?\b", re.I), OfflineRead("foundation", {"query_entity": "suppliers"}, "suppliers")),
    (re.compile(r"\bvehicles?|plate|fleet\b", re.I), OfflineRead("foundation", {"query_entity": "vehicles"}, "vehicles")),
]


def plan_offline_read(message: str) -> OfflineRead | None:
    if classify_turn(message) != "read":
        return None  # writes, memory changes and anything ambiguous are never guessed at
    return next((rule for pattern, rule in _RULES if pattern.search(message)), None)


def answer_offline(message: str, runner: Any, token: str, *, today: date | None = None) -> str | None:
    plan = plan_offline_read(message)
    if plan is None:
        return None
    result = runner.run(plan.agent, {"token": token, **plan.args})
    if result.status != "done":
        reason = result.state.get("halt_reason") or "the lookup did not complete"
        return f"**Couldn't fetch the {plan.label}.** {reason}\n\n{FOOTNOTE}"
    plate = (_PLATE.search(message.upper()) or [None, None])[1]
    return format_fallback_response(
        plan.args["query_entity"], result.state.get("query_result"), plate=plate, message=message, today=today or date.today()
    )


# --------------------------------------------------------------------------- formatting


def format_fallback_response(entity: str, data: Any, *, plate: str | None = None, message: str = "", today: date | None = None) -> str:
    """Markdown for a sub-agent read result. Pure Python, no LLM."""
    today = today or date.today()
    if entity == "fuel_logs" and plate:
        body = _fuel_summary(data or [], plate, message, today)
    elif entity == "service_due" and isinstance(data, dict):
        body = "\n\n".join([_list("Overdue service", data.get("overdue"), "service_due", plate, "none overdue"),
                            _list("Upcoming service", data.get("upcoming"), "service_due", plate, "none upcoming")])
    elif entity == "dashboard_summary" and isinstance(data, dict):
        body = _dashboard(data)
    else:
        body = _list(_TITLES.get(entity, _humanize(entity)), data, entity, plate, f"no {_humanize(entity).lower()} on record")
    return f"{body}\n\n{FOOTNOTE}"


def _num(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _amount(value: Any) -> str:
    n = _num(value)
    return f"{CURRENCY} {n:,.0f}" if n is not None else "-"


def _quantity(n: float) -> str:
    return f"{n:,.1f}".rstrip("0").rstrip(".")


def _km(value: Any) -> str:
    n = _num(value)
    return f"{n:,.0f} km" if n is not None else "-"


def _when(value: Any) -> str:
    text = str(value or "")
    try:
        d = datetime.fromisoformat(text.replace("Z", "+00:00")).date() if len(text) > 10 else date.fromisoformat(text[:10])
    except ValueError:
        return text
    return f"{d.day} {d:%b} {d.year}"


def _nice(value: Any) -> str:
    """oil_change -> Oil change; lists -> comma separated."""
    if isinstance(value, (list, tuple)):
        return ", ".join(_nice(v) for v in value)
    text = str(value).replace("_", " ").strip()
    return text[:1].upper() + text[1:]


def _humanize(key: str) -> str:
    return _nice(key)


def _fuel_summary(rows: list[dict[str, Any]], plate: str, message: str, today: date) -> str:
    """Totals for one vehicle. Distance is the odometer span between its first and last fill in
    the window, and cost per km is total cost over that distance. (The first fill in a window
    pays for driving that happened before it, so this slightly overstates cost per km.)"""
    mine = [r for r in rows if str(r.get("vehicle_plate", "")).upper() == plate]
    period = ""
    if re.search(r"\b(last|past|this)\s+month\b", message, re.I):
        since = (today - timedelta(days=30)).isoformat()
        mine = [r for r in mine if str(r.get("date", "")) >= since]
        period = " (Past Month)"
    title = f"**Fuel & Cost Summary for Vehicle {plate}{period}**"
    if not mine:
        return f"{title}\n* No fuel logs recorded for this period."

    litres = sum(_num(r.get("liters_filled")) or 0 for r in mine)
    cost = sum(_num(r.get("total_cost")) or 0 for r in mine)
    odometers = [v for v in (_num(r.get("odometer_reading")) for r in mine) if v is not None]
    distance = (max(odometers) - min(odometers)) if len(odometers) >= 2 else 0
    lines = [
        f"* **Total Fuel Consumed:** {_quantity(litres)} Liters",
        f"* **Total Fuel Cost:** {CURRENCY} {cost:,.0f}",
    ]
    if distance > 0:
        lines.append(f"* **Total Distance Covered:** {distance:,.0f} km ({min(odometers):,.0f} km → {max(odometers):,.0f} km)")
        lines.append(f"* **Average Cost per km:** {CURRENCY} {cost / distance:,.2f} / km")
    else:
        lines.append("* **Total Distance Covered:** not available (needs at least two fills)")
        lines.append("* **Average Cost per km:** not available")
    return "\n".join([title, *lines])


def _dashboard(data: dict[str, Any]) -> str:
    labels: list[tuple[str, str, Callable[[Any], str]]] = [
        ("total_vehicles", "Vehicles", str), ("active_drivers", "Active drivers", str),
        ("month_fuel_cost", "Fuel cost this month", _amount), ("overdue_maintenance_count", "Overdue maintenance", str),
        ("low_stock_parts_count", "Low-stock parts", str), ("open_incidents_count", "Open incidents", str),
    ]
    lines = [f"* **{label}:** {fmt(data[key])}" for key, label, fmt in labels if key in data]
    return "\n".join(["**Fleet Dashboard Summary**", *lines])


_TITLES = {
    "vehicles": "Vehicles", "drivers": "Drivers", "suppliers": "Suppliers", "fuel_logs": "Fuel logs", "trip_logs": "Trips",
    "maintenance_logs": "Maintenance history", "inventory": "Parts inventory", "low_stock": "Low-stock parts",
    "incidents": "Incidents", "fleet_health": "Fleet health",
}


def _list(title: str, data: Any, entity: str, plate: str | None, empty: str) -> str:
    rows = list(data or []) if not isinstance(data, dict) else [data]
    if plate:
        rows = [r for r in rows if plate in str(r.get("vehicle_plate", r.get("plate_number", ""))).upper()] or rows
    if not rows:
        return f"**{title}**\n* {empty[:1].upper() + empty[1:]}."
    row_format = _ROWS.get(entity, _generic_row)
    shown = [row_format(r) for r in rows[:MAX_ROWS]]
    more = [f"* …and {len(rows) - len(shown)} more"] if len(rows) > len(shown) else []
    return "\n".join([f"**{title} ({len(rows)})**", *[f"* {line}" for line in shown], *more])


def _join(*parts: str | None) -> str:
    return " · ".join(p for p in parts if p)


def _plate(r: dict[str, Any]) -> str:
    return str(r.get("vehicle_plate") or r.get("plate_number") or "Unknown vehicle")


def _due(r: dict[str, Any]) -> str:
    remaining = _num(r.get("km_remaining"))
    if remaining is not None and remaining < 0:
        state = f"{abs(remaining):,.0f} km overdue"
    elif remaining is not None:
        state = f"due in {remaining:,.0f} km"
    elif r.get("next_due_km") is not None:
        state = f"due at {_km(r.get('next_due_km'))}"
    else:
        state = None
    return _join(state, f"by {_when(r['next_due_date'])}" if r.get("next_due_date") else None)


_ROWS: dict[str, Callable[[dict[str, Any]], str]] = {
    "vehicles": lambda r: f"**{_plate(r)}** — " + _join(f"{r.get('make', '')} {r.get('model', '')}".strip(), _nice(r["status"]) if r.get("status") else None, _km(r["current_odometer"]) if r.get("current_odometer") is not None else None),
    "drivers": lambda r: f"**{r.get('full_name', 'Unknown driver')}** — " + _join(_nice(r["status"]) if r.get("status") else None, f"licence expires {_when(r['license_expiry'])}" if r.get("license_expiry") else None),
    "suppliers": lambda r: f"**{r.get('name', 'Unknown supplier')}** — " + _join(_nice(r["category"]) if r.get("category") else None, r.get("phone")),
    "fuel_logs": lambda r: f"**{_plate(r)}** ({_when(r.get('date'))}) — " + _join(f"{_quantity(_num(r.get('liters_filled')) or 0)} L", _amount(r.get("total_cost")), f"{CURRENCY} {_num(r['cost_per_km']):,.2f}/km" if _num(r.get("cost_per_km")) is not None else None),
    "trip_logs": lambda r: f"**{_plate(r)}** ({_when(r.get('start_time'))}) — " + _join(_km(r.get("distance_km")), f"driver {r['driver_name']}" if r.get("driver_name") else None),
    "maintenance_logs": lambda r: f"**{_plate(r)}** ({_when(r.get('date'))}) — " + _join(_nice(r.get("service_types") or r.get("service_type") or "Service"), _amount(r["cost"]) if r.get("cost") is not None else None),
    "inventory": lambda r: f"**{r.get('name', 'Part')}**" + (f" ({r['part_number']})" if r.get("part_number") else "") + " — " + _join(f"{r.get('qty_on_hand', '?')} in stock", f"reorder at {r['reorder_threshold']}" if r.get("reorder_threshold") is not None else None),
    "low_stock": lambda r: f"**{r.get('name', 'Part')}**" + (f" ({r['part_number']})" if r.get("part_number") else "") + " — " + _join(f"{r.get('qty_on_hand', '?')} in stock", f"reorder at {r['reorder_threshold']}" if r.get("reorder_threshold") is not None else None),
    "incidents": lambda r: f"**{_plate(r)}** ({_when(r.get('date'))}) — " + _join(_nice(r.get("incident_type", "Incident")), f"**{r['severity']}**" if r.get("severity") else None, _nice(r["resolution_status"]) if r.get("resolution_status") else None, (str(r["description"])[:60] + ("…" if len(str(r["description"])) > 60 else "")) if r.get("description") else None),
    "fleet_health": lambda r: f"**{_plate(r)}** — health score {r.get('health_score', '?')}/100",
    "service_due": lambda r: f"**{_plate(r)}** — " + _join(_nice(r.get("service_type", "Service")), _due(r)),
}


def _generic_row(row: dict[str, Any]) -> str:
    """Unknown record type: human labels, no ids, no field names."""
    pairs = [
        f"{_humanize(k)}: {_nice(v) if isinstance(v, str) else v}"
        for k, v in row.items()
        if not k.endswith("_id") and k != "id" and isinstance(v, (str, int, float)) and v != ""
    ]
    return ", ".join(pairs[:5])
