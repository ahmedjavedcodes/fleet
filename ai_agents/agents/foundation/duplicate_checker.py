"""PreSearchDuplicateSubAgent: proactive duplicate lookup before onboarding.

Per fleet-registry-agent.md FR 6 / Acceptance Criteria 3-4: checks the read
tools for an existing match before any create_*_tool call, to avoid
unnecessary 409s. The backend remains the final authority -- a race between
this pre-check and the create call can still 409; callers re-run the
matching find_duplicate_* function once on that error (AC 4) and report the
conflict, rather than retrying the create.

Each function accepts the get_*_tool as a parameter (rather than importing
mcp_server.foundation_tools directly) so callers -- and tests -- can inject
a fake without needing a live backend.
"""

from __future__ import annotations

from typing import Any, Callable

from tools.auth_context import AgentContext

VehicleLister = Callable[[AgentContext], list[dict[str, Any]]]
DriverLister = Callable[[AgentContext], list[dict[str, Any]]]
SupplierLister = Callable[[AgentContext], list[dict[str, Any]]]


def find_duplicate_vehicle(
    context: AgentContext, plate_number: str, *, get_vehicles: VehicleLister
) -> dict[str, Any] | None:
    if not plate_number:
        return None
    plate = plate_number.strip().upper()
    return next(
        (v for v in get_vehicles(context) if (v.get("plate_number") or "").strip().upper() == plate),
        None,
    )


def find_duplicate_driver(
    context: AgentContext, license_number: str, *, get_drivers: DriverLister
) -> dict[str, Any] | None:
    if not license_number:
        return None
    license_no = license_number.strip().upper()
    return next(
        (d for d in get_drivers(context) if (d.get("license_number") or "").strip().upper() == license_no),
        None,
    )


def find_duplicate_supplier(
    context: AgentContext, name: str, *, get_suppliers: SupplierLister
) -> dict[str, Any] | None:
    if not name:
        return None
    normalized = name.strip().casefold()
    return next(
        (s for s in get_suppliers(context) if (s.get("name") or "").strip().casefold() == normalized),
        None,
    )
