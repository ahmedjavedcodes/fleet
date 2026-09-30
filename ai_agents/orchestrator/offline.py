"""Last-resort answers when EVERY language model is unavailable.

A plain read ("which vehicles are due for service?", "fuel used by CD-5678 last month") does
not need an LLM to be answered: it needs the right sub-agent query and a formatter. This maps
a read-only question to one deterministic sub-agent query (through the normal runner, so RBAC,
org scoping and the backend's own checks all still apply) and formats the result. It never
writes: only query_entity reads are ever issued, and only for turns the read classifier accepts.

It is deliberately dumb. No planning, no multi-step reasoning, no natural-language analysis:
just the raw records (or a sum for the one calculation people ask for constantly, fuel totals),
clearly labelled as such. If no rule matches, it returns None and the caller shows the error.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Any

from orchestrator.turn_profile import classify_turn

_PLATE = re.compile(r"\b([A-Z]{2,3}-\d{3,4})\b")
MAX_ROWS = 8
PREAMBLE = "The AI model is unavailable right now, so this comes straight from the fleet records (no AI analysis)."


@dataclass(frozen=True)
class OfflineRead:
    agent: str
    args: dict[str, Any]
    label: str


# (pattern, agent, query args, label) -- first match wins, so specific rules come first.
_RULES: list[tuple[re.Pattern[str], OfflineRead]] = [
    (re.compile(r"\b(due|overdue|upcoming)\b.*\bservic|\bservic\w*\b.*\b(due|overdue)\b", re.I), OfflineRead("maintenance", {"query_entity": "service_due"}, "service due")),
    (re.compile(r"\blow[- ]stock|reorder", re.I), OfflineRead("maintenance", {"query_entity": "low_stock"}, "low-stock parts")),
    (re.compile(r"\b(parts?|inventory|spares?|stock)\b", re.I), OfflineRead("maintenance", {"query_entity": "inventory"}, "parts inventory")),
    (re.compile(r"\b(maintenance|repairs?)\b", re.I), OfflineRead("maintenance", {"query_entity": "maintenance_logs"}, "maintenance history")),
    (re.compile(r"\b(trips?|odometer|mileage)\b", re.I), OfflineRead("fuel", {"query_entity": "trip_logs"}, "trip logs")),
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
        return f"{PREAMBLE} I couldn't fetch the {plan.label}: {reason}"

    data = result.state.get("query_result")
    plate = (_PLATE.search(message.upper()) or [None, None])[1]
    if plan.args["query_entity"] == "fuel_logs" and plate:
        return f"{PREAMBLE}\n\n{_fuel_totals(data or [], plate, message, today or date.today())}"
    return f"{PREAMBLE}\n\n{_format(plan.label, data, plate)}"


def _num(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _fuel_totals(rows: list[dict[str, Any]], plate: str, message: str, today: date) -> str:
    mine = [r for r in rows if str(r.get("vehicle_plate", "")).upper() == plate]
    window = "all recorded fuel logs"
    if re.search(r"\b(last|past|this)\s+month\b", message, re.I):
        since = (today - timedelta(days=30)).isoformat()
        mine = [r for r in mine if str(r.get("date", "")) >= since]
        window = "the last 30 days"
    if not mine:
        return f"No fuel logs found for {plate} in {window}."
    litres = sum(_num(r.get("liters_filled")) or 0 for r in mine)
    cost = sum(_num(r.get("total_cost")) or 0 for r in mine)
    per_km = [v for v in (_num(r.get("cost_per_km")) for r in mine) if v is not None]
    average = f"average cost per km Rs {sum(per_km) / len(per_km):,.2f}" if per_km else "cost per km not available (no earlier odometer to compare with)"
    return f"{plate}, {window}: {len(mine)} fill(s), {litres:,.1f} L in total, Rs {cost:,.0f} spent, {average}."


def _format(label: str, data: Any, plate: str | None) -> str:
    if isinstance(data, dict) and {"overdue", "upcoming"} <= data.keys():
        return "\n\n".join(_format(f"{k} service", data[k], plate) for k in ("overdue", "upcoming"))
    if isinstance(data, dict):
        return f"{label}: " + ", ".join(f"{k}={v}" for k, v in data.items() if not isinstance(v, (dict, list)))
    rows = list(data or [])
    if plate:
        rows = [r for r in rows if plate in str(r.get("vehicle_plate", r.get("plate_number", ""))).upper()] or rows
    if not rows:
        return f"No {label} on record."
    shown = [_row(r) for r in rows[:MAX_ROWS]]
    more = f"\n(showing {len(shown)} of {len(rows)})" if len(rows) > len(shown) else ""
    return f"{label} ({len(rows)}):\n" + "\n".join(f"- {line}" for line in shown) + more


def _row(row: dict[str, Any]) -> str:
    keys = [k for k, v in row.items() if not k.endswith("_id") and k != "id" and isinstance(v, (str, int, float)) and v != ""]
    return ", ".join(f"{k}={row[k]}" for k in keys[:7])
