import uuid
from datetime import date as date_type
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel

from app.models.enums import ServiceType


class DashboardSummaryResponse(BaseModel):
    total_vehicles: int
    active_drivers: int
    month_fuel_cost: Decimal
    overdue_maintenance_count: int
    low_stock_parts_count: int
    open_incidents_count: int


class FuelTrendPoint(BaseModel):
    month: str
    total_cost: Decimal
    avg_cost_per_km: Decimal | None


# A plain array, consistent with the FleetComplianceMatrixResponse/
# TimelineResponse convention used elsewhere in this API.
FuelTrendsResponse = list[FuelTrendPoint]


class MaintenanceCalendarItem(BaseModel):
    vehicle_id: uuid.UUID
    plate_number: str
    service_type: ServiceType
    vehicle_name: str | None = None
    driver_name: str | None = None
    last_service_date: date_type | None = None
    # Nullable: an item overdue purely by km (no service_interval_months
    # configured on the vehicle) has no next_due_date at all. Per EC-2, an
    # overdue item is never dropped from the calendar for any reason
    # (including "we can't date it") -- it stays, with due_date=None and
    # due_km/status conveying the urgency instead. The plan's schema states
    # `due_date: date` (non-nullable); this is a deliberate, documented
    # deviation rather than fabricating a date or silently hiding the item.
    due_date: date_type | None
    due_km: int | None
    status: Literal["upcoming", "overdue"]


MaintenanceCalendarResponse = list[MaintenanceCalendarItem]


class VehicleHealthSignals(BaseModel):
    compliance: int | None
    incidents: int | None
    maintenance_currency: int | None
    fuel_efficiency: int | None


class VehicleHealthScore(BaseModel):
    vehicle_id: uuid.UUID
    plate_number: str
    health_score: int
    signals: VehicleHealthSignals
    # Raw inputs behind the fuel_efficiency signal (average cost per km over the
    # last 3 months and the 3 months before). The signal is null unless both
    # exist, so these let the UI still show the current figure on its own.
    current_cost_per_km: Decimal | None = None
    previous_cost_per_km: Decimal | None = None


FleetHealthResponse = list[VehicleHealthScore]
