"""A structured summary of what an approval card is about to do.

The approval card used to say only which tool was waiting ("fuel"). Here the paused sub-agent's own state is turned
into labelled rows -- vehicle, service type, description, cost -- so the approver sees exactly what will be written.
Pure formatting: nothing is looked up, and secrets or binary data in the state are never read.
"""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from typing import Any

Row = dict[str, str]


def _text(value: Any) -> str | None:
    if value is None or value == "" or value == [] or value == {}:
        return None
    if isinstance(value, (datetime, date)):
        return value.isoformat(sep=" ", timespec="minutes") if isinstance(value, datetime) else value.isoformat()
    if isinstance(value, (list, tuple)):
        return ", ".join(filter(None, (_text(v) for v in value))) or None
    if hasattr(value, "value"):  # enums
        return str(value.value).replace("_", " ")
    return str(value)


def _number(value: Any, digits: int = 2) -> str | None:
    try:
        number = Decimal(str(value)).quantize(Decimal(1) if digits == 0 else Decimal(10) ** -digits)
    except (InvalidOperation, ValueError):
        return _text(value)
    text = f"{number:,}"
    return text.rstrip("0").rstrip(".") if "." in text else text


def _money(value: Any) -> str | None:
    amount = _number(value)
    return f"Rs {amount}" if amount is not None else None


def _rows(pairs: list[tuple[str, str | None]]) -> list[Row]:
    return [{"label": label, "value": value} for label, value in pairs if value]


def _title(value: Any) -> str | None:
    text = _text(value)
    return text[:1].upper() + text[1:] if text else None


def _fuel(state: dict[str, Any]) -> list[Row]:
    if isinstance(state.get("trip_fields"), dict):
        t = state["trip_fields"]
        return _rows([
            ("Vehicle ID", _text(t.get("vehicle_id"))), ("Driver ID", _text(t.get("driver_id"))),
            ("Start", _text(t.get("start_time"))), ("End", _text(t.get("end_time"))),
            ("Start odometer", _number(t.get("start_odometer"), 0) and f"{_number(t.get('start_odometer'), 0)} km"),
            ("End odometer", _number(t.get("end_odometer"), 0) and f"{_number(t.get('end_odometer'), 0)} km"),
            ("Fuel used", t.get("fuel_consumed") is not None and f"{_number(t.get('fuel_consumed'))} L" or None),
            ("Notes", _text(t.get("notes"))),
        ])
    r = state.get("sanitized") or {}
    return _rows([
        ("Vehicle", _text(state.get("vehicle_plate")) or _text(r.get("vehicle_id"))),
        ("Date", _text(r.get("date"))),
        ("Station", _text(r.get("fuel_station_name"))),
        ("Odometer", r.get("odometer_reading") is not None and f"{_number(r.get('odometer_reading'), 0)} km" or None),
        ("Liters", r.get("liters_filled") is not None and f"{_number(r.get('liters_filled'))} L" or None),
        ("Price per liter", _money(r.get("price_per_liter"))),
        ("Total cost", _money(r.get("total_cost"))),
        ("Slip ID", _text(r.get("slip_id"))), ("PO number", _text(r.get("po_number"))),
        ("Payment", _text(r.get("payment_method"))), ("Card", _text(r.get("card_used"))),
        ("Notes", _text(r.get("notes"))),
    ])


def _maintenance(state: dict[str, Any]) -> list[Row]:
    e = state.get("extracted") or {}
    if e.get("line_items") is not None:  # a parts invoice
        items = [
            f"{i.get('name_or_sku') or i.get('part_number') or i.get('name') or 'part'} x{_number(i.get('qty') or i.get('quantity'), 0)}"
            for i in e["line_items"] if isinstance(i, dict)
        ]
        return _rows([("Parts received", "; ".join(items) or None)])
    parts = [f"{i.get('name_or_sku')} x{_number(i.get('qty'), 0)}" for i in e.get("parts_used") or [] if isinstance(i, dict)]
    return _rows([
        ("Vehicle", _text(e.get("vehicle_plate"))),
        ("Odometer", e.get("odometer") is not None and f"{_number(e.get('odometer'), 0)} km" or None),
        ("Service type", (_text(e.get("service_types") or e.get("service_type")) or "").replace("_", " ") or None),
        ("Service scale", _title(e.get("service_scale"))),
        ("Description", _text(e.get("issue_description"))),
        ("Parts used", "; ".join(parts) or None),
        ("Labor hours", _number(e.get("labor_hours"))),
        ("Total cost", _money(e.get("cost"))),
        ("Driver", _text(e.get("driver_name"))),
    ])


def _incident(state: dict[str, Any]) -> list[Row]:
    e = state.get("extracted") or {}
    return _rows([
        ("Vehicle", _text(e.get("vehicle_plate"))), ("Driver", _text(e.get("driver_name"))),
        ("Incident type", _title(e.get("incident_type"))),
        ("Severity", _title(state.get("severity") or e.get("severity"))),
        ("When", _text(e.get("incident_time") or e.get("incident_date"))),
        ("Location", _text(e.get("location_area") or e.get("location"))),
        ("Description", _text(e.get("damage_description"))), ("Remarks", _text(e.get("remarks"))),
        ("Photo attached", "Yes" if state.get("attachment_url") or e.get("attachment_url") else None),
    ])


def _assignment(state: dict[str, Any]) -> list[Row]:
    if state.get("intent") == "terminate_assignment":
        r = state.get("terminate_request") or {}
        return _rows([
            ("Action", "Release the vehicle"), ("Vehicle", _text(r.get("vehicle_plate"))),
            ("Released at", _text(r.get("released_at"))),
            ("End odometer", r.get("end_odometer") is not None and f"{_number(r.get('end_odometer'), 0)} km" or None),
            ("Condition", _title(r.get("leave_condition"))), ("Notes", _text(r.get("leave_notes"))),
        ])
    r = state.get("assign_request") or {}
    return _rows([
        ("Action", "Assign the vehicle to a driver"), ("Vehicle", _text(r.get("vehicle_plate"))), ("Driver", _text(r.get("driver_name"))),
        ("Assigned at", _text(r.get("assigned_at"))),
        ("Start odometer", r.get("start_odometer") is not None and f"{_number(r.get('start_odometer'), 0)} km" or None),
        ("Condition", _title(r.get("take_condition"))), ("Notes", _text(r.get("take_notes"))),
    ])


_HIDDEN = {"password", "token", "vehicle_id", "driver_id", "organization_id"}


def _registry(state: dict[str, Any]) -> list[Row]:
    kind = _title(state.get("document_type"))
    rows = [("Record", kind.replace("_", " ") if kind else None)]
    for key, value in (state.get("sanitized") or {}).items():
        if key not in _HIDDEN and (text := _text(value)):
            rows.append((key.replace("_", " ").capitalize(), text))
    return _rows(rows)


_BUILDERS = {"fuel": _fuel, "maintenance": _maintenance, "accountability": _incident, "assignment": _assignment, "foundation": _registry}
_ACTIONS = {
    "fuel": "Record this fuel entry?", "maintenance": "Record this maintenance entry?", "accountability": "File this incident report?",
    "assignment": "Make this assignment change?", "foundation": "Add this record to the registry?",
}


def summarize_pending(agent_name: str, state: dict[str, Any]) -> list[Row]:
    """Labelled rows describing the pending write; empty when nothing useful can be said."""
    build = _BUILDERS.get(agent_name)
    if build is None:
        return []
    try:
        return build(state)
    except Exception:  # noqa: BLE001 -- a summary is a courtesy: the approval must still be shown without one
        return []


def approval_question(agent_name: str) -> str | None:
    return _ACTIONS.get(agent_name)
