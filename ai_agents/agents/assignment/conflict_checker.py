"""Assignment-conflict guardrails for the Assignment Agent.

Per assignment-agent.md FR 3 / AC 3: halts before create_assignment_tool
when the target vehicle or driver already has an active assignment, and
before terminate_assignment_tool when the target vehicle has none. These
are fail-fast UX layers only -- backend/app/services/assignment_service.py
already enforces all three itself (409 "Vehicle/Driver already has an
active assignment", 404 "No active assignment found"), so a race between
this pre-check and the actual call is still possible and must be handled
by the caller (see graph.py's handling of that 409/404, matching the
Fleet Registry Agent's duplicate-check precedent).

"Active" is real-time custody: an assignment with released_at is None
(backend/app/models/assignment.py; root CLAUDE.md's custody model).
"""

from __future__ import annotations

from typing import Any


class AssignmentConflictError(Exception):
    """Raised when the target vehicle/driver already has (or lacks) an active assignment."""


def check_vehicle_available(vehicle_history: list[dict[str, Any]]) -> None:
    if any(a.get("released_at") is None for a in vehicle_history):
        raise AssignmentConflictError("This vehicle already has an active assignment.")


def check_driver_available(driver_history: dict[str, Any]) -> None:
    if driver_history.get("current_assignment") is not None:
        raise AssignmentConflictError("This driver already has an active assignment.")


def check_vehicle_has_active_assignment(vehicle_history: list[dict[str, Any]]) -> None:
    if not any(a.get("released_at") is None for a in vehicle_history):
        raise AssignmentConflictError("No active assignment found for this vehicle.")
