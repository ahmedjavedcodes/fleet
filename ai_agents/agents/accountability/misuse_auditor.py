"""Off-hours trip auditing for the Driver Accountability Agent.

The plan (Plans/Driver_Accountability_Agent.md, FR 3) calls this "Misuse &
Geofence Auditing" and asks to check trips against "authorized schedules or
operating bounds". Geofencing is impossible in this system: the root
CLAUDE.md constraint is explicit that there is no real-time hardware, IoT,
or GPS integration anywhere, and there is no stored concept of "authorized
schedule" or "operating bounds" anywhere in the backend (verified: no
geofence/shift-schedule/business-hours model exists). The only data
available is each TripLog's start_time/end_time (backend/app/schemas/
accountability.py's TripLogResponse).

So this is a plain time-window heuristic over existing trip timestamps, not
geofencing or true misuse detection: a trip starting or ending outside the
given hour window is flagged "off_hours". It is a proxy signal for a human
to review, not a verdict -- a heuristic can't distinguish an authorized
early-morning delivery from actual misuse.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

DEFAULT_START_HOUR = 6
DEFAULT_END_HOUR = 22


def audit_trips_for_off_hours(
    trips: list[dict[str, Any]], *, start_hour: int = DEFAULT_START_HOUR, end_hour: int = DEFAULT_END_HOUR
) -> list[dict[str, Any]]:
    """Returns the subset of trips whose start_time or end_time falls
    outside [start_hour, end_hour), each with a "reason" key attached.
    """
    flagged = []
    for trip in trips:
        start = _parse(trip.get("start_time"))
        end = _parse(trip.get("end_time"))

        reasons = []
        if start is not None and not (start_hour <= start.hour < end_hour):
            reasons.append(f"started at {start.strftime('%H:%M')}, outside {start_hour:02d}:00-{end_hour:02d}:00")
        if end is not None and not (start_hour <= end.hour < end_hour):
            reasons.append(f"ended at {end.strftime('%H:%M')}, outside {start_hour:02d}:00-{end_hour:02d}:00")

        if reasons:
            flagged.append({**trip, "reason": "; ".join(reasons)})

    return flagged


def _parse(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        return value
    if isinstance(value, str):
        try:
            return datetime.fromisoformat(value)
        except ValueError:
            return None
    return None
