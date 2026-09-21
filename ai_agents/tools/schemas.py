"""Pydantic v2 models for the Fleet Registry Agent.

Deliberately duplicates the minimal shape of the backend's create schemas
(backend/app/schemas/{vehicle,driver,supplier}.py) rather than importing
them -- per CLAUDE.md's cross-module boundary rule, ai_agents/ never imports
backend code. These are allowed to drift slightly since one validates HTTP
input and the other validates tool input.
"""

from __future__ import annotations

from datetime import date
from enum import Enum

from pydantic import BaseModel, ConfigDict


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
