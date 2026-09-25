"""Pydantic v2 models for the Fleet Registry Agent.

Deliberately duplicates the minimal shape of the backend's create schemas
(backend/app/schemas/{vehicle,driver,supplier}.py) rather than importing
them -- per CLAUDE.md's cross-module boundary rule, ai_agents/ never imports
backend code. These are allowed to drift slightly since one validates HTTP
input and the other validates tool input.
"""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from enum import Enum

from pydantic import BaseModel, ConfigDict, Field


class VehicleFuelType(str, Enum):
    diesel = "diesel"
    petrol = "petrol"
    hybrid = "hybrid"
    electric = "electric"


# ---- create-tool inputs: the bridged, sanitized, backend-ready shape ----
# Field names match the backend's *Create schemas exactly (see FR 8's
# extraction -> backend field-name bridge: first_name+last_name -> full_name,
# phone_number -> phone, expiration_date -> license_expiry,
# initial_odometer -> current_odometer).


class VehicleCreateInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    plate_number: str
    make: str
    model: str
    year: int
    vin: str
    fuel_type: VehicleFuelType
    current_odometer: int = 0


class DriverCreateInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    full_name: str
    license_number: str
    license_expiry: date
    phone: str


class SupplierCreateInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str
    contact_email: str | None = None
    phone: str | None = None


# ---- vision extraction outputs: raw, pre-bridge, pre-sanitize ----
# Every field is optional -- a None means the vision model couldn't read it,
# which callers must treat as an extraction gap, not a valid empty value.


class LicenseExtraction(BaseModel):
    first_name: str | None = None
    last_name: str | None = None
    license_number: str | None = None
    phone_number: str | None = None
    expiration_date: date | None = None


class VehicleDocExtraction(BaseModel):
    plate_number: str | None = None
    make: str | None = None
    model: str | None = None
    year: int | None = None
    vin: str | None = None
    initial_odometer: int | None = None


class SupplierDocExtraction(BaseModel):
    name: str | None = None
    contact_email: str | None = None
    phone: str | None = None


# ---- Fuel Agent: create-tool inputs ----
# Field names match backend/app/schemas/fuel.py's FuelLogCreate and
# backend/app/schemas/accountability.py's TripLogCreate exactly -- see
# fuel-agent.md FR 3's extraction -> backend field-name bridge
# (liters -> liters_filled, odometer -> odometer_reading, receipt_date ->
# date, plus a derived price_per_liter the extraction schema never produces).


class FuelLogCreateInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    vehicle_id: str
    driver_id: str | None = None
    date: date
    odometer_reading: int
    liters_filled: Decimal
    price_per_liter: Decimal
    total_cost: Decimal
    notes: str | None = None


class TripLogCreateInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    driver_id: str
    vehicle_id: str
    start_time: datetime
    end_time: datetime
    start_odometer: int
    end_odometer: int
    fuel_consumed: Decimal | None = None
    notes: str | None = None


# ---- Fuel Agent: vision extraction output ----


class FuelReceiptExtraction(BaseModel):
    station_name: str | None = None
    receipt_date: date | None = None
    liters: float | None = None
    total_cost: float | None = None
    odometer: int | None = None
    plate_number: str | None = None


# ---- Maintenance & Parts Inventory Agent: mirrors backend/app/models/enums.py
# ServiceType exactly. ----


class ServiceType(str, Enum):
    oil_change = "oil_change"
    brake_service = "brake_service"
    tire_rotation = "tire_rotation"
    engine_repair = "engine_repair"
    transmission = "transmission"
    electrical = "electrical"
    body_work = "body_work"
    general_inspection = "general_inspection"
    other = "other"


# ---- Maintenance Agent: vision/text extraction output ----


class PartLineItem(BaseModel):
    """Raw, human-readable line item -- name_or_sku is resolved against
    get_inventory_tool into a real part_id before it can be submitted
    anywhere (see ResolvedPartUsed)."""

    name_or_sku: str | None = None
    qty: int | None = None


class WorkOrderExtraction(BaseModel):
    issue_description: str | None = None
    service_type: str | None = None
    parts_used: list[PartLineItem] = Field(default_factory=list)
    labor_hours: float | None = None
    cost: float | None = None
    vehicle_plate: str | None = None
    odometer: int | None = None


class InvoiceLineItem(BaseModel):
    part_number: str | None = None
    name: str | None = None
    qty_received: int | None = None
    unit_cost: float | None = None


class PartsInvoiceExtraction(BaseModel):
    line_items: list[InvoiceLineItem] = Field(default_factory=list)


# ---- Maintenance Agent: create-tool inputs ----
# Field names match backend/app/schemas/maintenance.py's MaintenanceLogCreate
# and MechanicReportCreate, and backend/app/schemas/inventory.py's
# PartsInventoryUpdate, exactly.


class MaintenanceLogCreateInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    vehicle_id: str
    date: date
    odometer_at_service: int
    service_type: ServiceType
    description: str | None = None
    cost: Decimal | None = None
    mechanic_name: str | None = None


class ResolvedPartUsed(BaseModel):
    part_id: str
    qty: int


class MechanicReportCreateInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    diagnostic_notes: str | None = None
    findings: str | None = None
    actions_taken: str | None = None
    parts_used: list[ResolvedPartUsed] = Field(default_factory=list)
    recommendations: str | None = None


class InventoryUpdateInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    qty_on_hand: int


# ---- Driver Accountability Agent: mirrors backend/app/models/enums.py
# IncidentType and IncidentSeverity exactly. ----


class IncidentType(str, Enum):
    damage = "damage"
    violation = "violation"
    near_miss = "near_miss"


class IncidentSeverity(str, Enum):
    minor = "minor"
    moderate = "moderate"
    severe = "severe"
    critical = "critical"


# ---- Driver Accountability Agent: vision/text extraction output ----


class IncidentExtraction(BaseModel):
    incident_date: date | None = None
    location: str | None = None
    severity: str | None = None
    # Not in the plan's extraction targets, but IncidentLogCreate.incident_type
    # is required and has no default -- the model must classify it too (see
    # driver-accountability-agent.md FR 1's correction).
    incident_type: str | None = None
    vehicle_plate: str | None = None
    driver_name: str | None = None
    damage_description: str | None = None


# ---- Driver Accountability Agent: create-tool input ----
# Field names match backend/app/schemas/accountability.py's IncidentLogCreate
# exactly. driver_id is optional at the schema level -- an incident can be
# filed with no driver attached -- but the graph still resolves and fills it
# from driver_name when possible, and always overrides it to the caller's
# own Driver.id for a driver-role caller (see graph.py).


class IncidentCreateInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    driver_id: str | None = None
    vehicle_id: str
    incident_type: IncidentType
    date: date
    severity: IncidentSeverity
    description: str
    location_description: str | None = None
    estimated_cost: Decimal | None = None


# ---- Assignment Agent: mirrors backend/app/models/enums.py VehicleCondition
# exactly. ----


class VehicleCondition(str, Enum):
    good = "good"
    fair = "fair"
    poor = "poor"


# ---- Assignment Agent: create-tool inputs ----
# Field names match backend/app/schemas/assignment.py's VehicleAssignRequest
# and VehicleReleaseRequest exactly. Both are vehicle-scoped in the real
# backend (POST /api/v1/vehicles/{vehicle_id}/assign|release) -- vehicle_id
# is a path parameter, not a body field, which is why neither model
# includes it; see mcp_server/assignment_tools.py.


class AssignmentCreateInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    driver_id: str
    assigned_at: datetime
    start_odometer: int
    take_condition: VehicleCondition
    take_notes: str | None = None


class AssignmentTerminateInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    released_at: datetime
    end_odometer: int
    leave_condition: VehicleCondition
    leave_notes: str | None = None
