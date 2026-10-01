"""Required-field check before any write: ask the user, never run an incomplete mutation.

A write tool called with details missing used to either halt deep inside the sub-agent ("Could not determine ...") or
reach an approval card with blanks. Here the orchestrator checks the obvious required parameters first. If one is
missing from BOTH the tool call and what the user attached this turn, the sub-agent is not run: the model gets an
observation telling it to ask the user, in chat, for exactly those items.

Only what can be known without reading the document is checked here (a typed fuel log, an assignment, a registry
document with no photo ...). What only the extraction can tell -- the odometer on a work order, the plate on a
receipt -- is caught when the sub-agent halts; see needs_user_input().
"""

from __future__ import annotations

import re
from datetime import datetime
from typing import Any

# Friendly names for the things a user can be asked for.
LABELS = {
    "vehicle_id": "the vehicle (plate number)",
    "vehicle_plate": "the vehicle's plate number",
    "driver_id": "the driver",
    "driver_name": "the driver's name",
    "date": "the date",
    "odometer_reading": "the exact odometer reading",
    "liters_filled": "the liters filled",
    "price_per_liter": "the price per liter",
    "total_cost": "the total cost",
    "start_odometer": "the odometer reading at the start",
    "end_odometer": "the odometer reading at the end",
    "take_condition": "the vehicle's condition when taken (good, fair or poor)",
    "leave_condition": "the vehicle's condition when returned (good, fair or poor)",
}


def _blank(value: Any) -> bool:
    return value is None or (isinstance(value, str) and not value.strip())


def _names(fields: list[str]) -> list[str]:
    return [LABELS.get(f, f.replace("_", " ")) for f in fields]


def missing_fields(agent: str, args: dict[str, Any], *, has_image: bool) -> list[str]:
    """Human-readable names of what a WRITE call to `agent` still needs from the user (empty = nothing known to be missing)."""
    if agent == "fuel":
        fields = args.get("fuel_fields")
        if args.get("trip_fields") is not None or args.get("query_entity"):
            return []
        if fields is None and not args.get("document_type"):
            return []
        fields = fields or {}
        if has_image:
            return []  # the receipt supplies what is missing; whatever it cannot show comes back as a halt
        # date (today) and odometer (the vehicle's last reading) are defaulted by the sub-agent, never asked for.
        absent = [f for f in ("vehicle_id",) if _blank(fields.get(f))]
        amounts = [f for f in ("liters_filled", "price_per_liter", "total_cost") if _blank(fields.get(f))]
        if len(amounts) > 1:  # two of the three give the third
            absent += amounts
        return _names(absent)

    if agent == "assignment":
        absent = []
        if (request := args.get("assign_request")) is not None:
            absent = [f for f in ("vehicle_plate", "driver_name") if _blank(request.get(f))]
        elif (request := args.get("terminate_request")) is not None:
            absent = [f for f in ("vehicle_plate",) if _blank(request.get(f))]
        return _names(absent)

    if agent == "maintenance" and args.get("document_type") and not has_image and _blank(args.get("document_text")):
        return ["the work order or parts invoice details (a photo, or the text: vehicle plate, odometer, services, cost)"]

    if agent == "accountability" and args.get("document_type") == "incident_report" and not has_image and _blank(args.get("document_text")):
        return ["a description of the incident (what happened, when, where, which vehicle)"]

    if agent == "foundation" and args.get("document_type") and not has_image and not args.get("provided_fields"):
        return ["a photo of the document"]

    return []


def not_run_observation(agent: str, missing: list[str]) -> str:
    return (
        f"{agent} NOT RUN -- missing required information: {'; '.join(missing)}. Ask for ALL of these in ONE short "
        "message. When the user answers, call this same tool again at once with their earlier details plus the answer "
        "merged in (for a typed work order, append it to document_text); ask nothing else first."
    )


_NEEDS_INPUT = re.compile(r"could not determine|requires |not provided|invalid (?:fuel|trip)_fields|missing", re.IGNORECASE)


def needs_user_input(halt_reason: str | None) -> bool:
    """A sub-agent halt that is really "I still need something from the user", as opposed to a refusal or an error."""
    return bool(halt_reason and _NEEDS_INPUT.search(halt_reason))


def needs_input_observation(agent: str, halt_reason: str) -> str:
    return (
        f"{agent} halted and needs more information from the user: {halt_reason} Ask for everything missing in ONE "
        "short message; do not guess. When they answer, call this same tool again at once with their earlier details "
        "plus the answer merged in (a typed work order: append it to document_text); never ask them for a record type."
    )


_PLATE = re.compile(r"\b[A-Z]{2,3}-\d{3,4}\b", re.IGNORECASE)
_TYPED_NOTE_AGENTS = ("maintenance", "accountability")
_NOTE_TYPE = {"maintenance": "work_order", "accountability": "incident_report"}


def merge_typed_note(agent: str, args: dict[str, Any], *, user_message: str, pending: dict[str, str]) -> dict[str, Any]:
    """Keep a typed work order / incident note whole across turns, whatever the model happened to put in the call.

    The model decides what goes in `document_text`, and in practice it drops the plate the user named or, on the
    answer to a follow-up ("odometer 45000"), sends only the new fragment. So: the note held back from the previous
    turn (`pending`) is put in front of a call that does not already contain it, and a plate in the user's message
    that the note lacks is appended. Anything else is left exactly as the model wrote it."""
    held = pending.get(agent)
    if agent not in _TYPED_NOTE_AGENTS or args.get("query_entity"):
        return args
    if not args.get("document_type"):
        # The answer to a follow-up often comes back as a bare call with no document_type, which the sub-agent would
        # read as a query ("missing query_entity"). A held-back note, or a typed note, has a known type.
        if not (held or args.get("document_text")):
            return args
        args = {**args, "document_type": _NOTE_TYPE[agent]}
    text = str(args.get("document_text") or "").strip()
    if held and held.casefold() not in text.casefold():
        text = f"{held.rstrip('. ')}. {text or user_message}".strip()
    plate = _PLATE.search(user_message or "")
    if agent == "maintenance" and plate and plate.group(0).upper() not in text.upper():
        text = f"{text}. Vehicle {plate.group(0).upper()}" if text else f"Vehicle {plate.group(0).upper()}"
    return {**args, "document_text": text} if text else args


def fill_defaults(agent: str, args: dict[str, Any], *, now: datetime) -> dict[str, Any]:
    """The one default that is safe: an assignment taken or released "now" when no time was given."""
    out = dict(args)
    if agent == "assignment":
        for key, stamp in (("assign_request", "assigned_at"), ("terminate_request", "released_at")):
            if out.get(key) is not None and _blank(out[key].get(stamp)):
                out[key] = {**out[key], stamp: now.isoformat(timespec="seconds")}
    return out
