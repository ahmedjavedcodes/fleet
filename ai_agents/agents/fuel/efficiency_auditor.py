"""Odometer continuity guardrail for the Fuel Agent.

Per fuel-agent.md FR 4 / AC 2: halts a fuel-receipt onboarding before any
create call when the receipt's odometer reading isn't strictly greater than
the vehicle's last recorded odometer. This is an agent-layer-only check --
backend/app/services/fuel_service.py's create_fuel_log does NOT reject a
lower odometer_reading; it silently skips updating Vehicle.current_odometer
while still creating the log. A caller hitting /api/v1/fuel directly still
bypasses this guardrail entirely -- fixing that is a backend change, out of
scope here.

Anomaly detection (is_anomalous, cost_per_km) is deliberately NOT
recomputed here -- the backend already computes both and this agent only
ever surfaces that response field, never a second, possibly-drifting
calculation (fuel-agent.md FR 5).
"""

from __future__ import annotations


class OdometerContinuityError(Exception):
    """Raised when a fuel receipt's odometer reading doesn't advance the vehicle's."""


def check_odometer_continuity(odometer_reading: int | None, current_odometer: int) -> None:
    """Raises OdometerContinuityError unless odometer_reading > current_odometer.

    A None reading (extraction couldn't read it) is treated as a violation
    too -- there's nothing to validate continuity against.
    """
    if odometer_reading is None:
        raise OdometerContinuityError("Could not determine the receipt's odometer reading.")
    if odometer_reading <= current_odometer:
        raise OdometerContinuityError(
            f"Odometer reading {odometer_reading} does not advance past the vehicle's current reading {current_odometer}."
        )
