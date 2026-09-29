"""Tool-schema / graph sync for the backend's expand_fleet_operational_fields
migration: the agents must be able to read AND write the new keys
(engine_number, slip_id, service_scale, ...), and the LLM-facing tool
descriptions must name them so the routing model knows to fill them in.

Extraction is faked (no live Groq call) and creators capture the payload they
are handed, so these tests assert on exactly what would be POSTed to the
backend."""

from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

import jwt
import pytest
from pydantic import ValidationError

from agents.accountability.graph import AccountabilityAgentDeps, get_compiled_accountability_graph
from agents.foundation.graph import FoundationAgentDeps, get_compiled_foundation_graph
from agents.fuel.graph import FuelAgentDeps, get_compiled_fuel_graph
from agents.maintenance.graph import MaintenanceAgentDeps, get_compiled_maintenance_graph
from orchestrator.graph import _is_read_only_call
from orchestrator.tool_schemas import (
    AccountabilityToolInput,
    AssignmentToolInput,
    FoundationToolInput,
    FuelToolInput,
    MaintenanceToolInput,
)
from tools.schemas import (
    DriverCreateInput,
    FuelLogCreateInput,
    FuelReceiptExtraction,
    IncidentCreateInput,
    IncidentExtraction,
    LicenseExtraction,
    MaintenanceLogCreateInput,
    SupplierCreateInput,
    SupplierDocExtraction,
    VehicleCreateInput,
    VehicleDocExtraction,
    WorkOrderExtraction,
)


def _token(role: str = "admin", sub: str = "user-1") -> str:
    payload = {"sub": sub, "org": "org-1", "role": role, "exp": datetime.now(timezone.utc) + timedelta(minutes=30)}
    return jwt.encode(payload, "irrelevant-signing-key", algorithm="HS256")


class _Capture:
    """Creator stand-in: records the validated input model it receives."""

    def __init__(self) -> None:
        self.calls: list = []

    def __call__(self, context, *args):
        data = args[-1]
        self.calls.append(data.model_dump(mode="json"))
        return {"id": "new", **self.calls[-1]}


# --- Create-input schemas -------------------------------------------------------------


def test_vehicle_input_carries_new_fields_and_defaults_ownership_to_owner() -> None:
    minimal = VehicleCreateInput(plate_number="A", make="m", model="x", year=2020, vin="V", fuel_type="diesel")
    assert minimal.model_dump(mode="json")["ownership_type"] == "owner"
    assert minimal.engine_number is None and minimal.chassis_number is None

    full = VehicleCreateInput(
        plate_number="A", make="m", model="x", year=2020, vin="V", fuel_type="diesel",
        engine_number="E1", chassis_number="C1", ownership_type="leasing",
    )
    assert full.model_dump(mode="json")["ownership_type"] == "leasing"
    with pytest.raises(ValidationError):
        VehicleCreateInput(
            plate_number="A", make="m", model="x", year=2020, vin="V", fuel_type="diesel", ownership_type="stolen"
        )
    # added_by is server-set; the agent must not be able to send it.
    with pytest.raises(ValidationError):
        VehicleCreateInput(plate_number="A", make="m", model="x", year=2020, vin="V", fuel_type="diesel", added_by="u")


def test_driver_and_supplier_inputs() -> None:
    driver = DriverCreateInput(
        full_name="A B", license_number="L", license_expiry="2030-01-01", phone="1",
        license_type="HTV", license_issue_date="2020-02-02", license_current_status="valid",
    )
    assert driver.license_issue_date == date(2020, 2, 2)
    with pytest.raises(ValidationError):  # drivers deliberately have no address
        DriverCreateInput(full_name="A", license_number="L", license_expiry="2030-01-01", phone="1", address="x")

    supplier = SupplierCreateInput(name="S", address="1 Road", category="tire_supplier")
    assert supplier.model_dump(mode="json")["category"] == "tire_supplier"
    assert SupplierCreateInput(name="S").model_dump(mode="json")["category"] == "other"
    with pytest.raises(ValidationError):
        SupplierCreateInput(name="S", category="bakery")


def test_fuel_log_input_carries_slip_fields() -> None:
    log = FuelLogCreateInput(
        vehicle_id="v", date="2026-09-01", odometer_reading=10, liters_filled=Decimal("5"),
        price_per_liter=Decimal("2"), total_cost=Decimal("10"),
        po_number="PO1", payment_method="card", card_used="**** 1111", fuel_station_name="Shell", slip_id="S1",
    )
    dumped = log.model_dump(mode="json")
    assert (dumped["po_number"], dumped["payment_method"], dumped["card_used"]) == ("PO1", "card", "**** 1111")
    assert (dumped["fuel_station_name"], dumped["slip_id"]) == ("Shell", "S1")


def test_maintenance_input_many_services_and_legacy_shorthand() -> None:
    many = MaintenanceLogCreateInput(
        vehicle_id="v", date="2026-09-01", odometer_at_service=10,
        service_types=["oil_change", "brake_service"], service_scale="major", driver_id="d1",
    )
    dumped = many.model_dump(mode="json")
    assert dumped["service_types"] == ["oil_change", "brake_service"]
    assert (dumped["service_scale"], dumped["driver_id"]) == ("major", "d1")
    assert "service_type" not in dumped

    legacy = MaintenanceLogCreateInput(
        vehicle_id="v", date="2026-09-01", odometer_at_service=10, service_type="electrical"
    )
    assert legacy.model_dump(mode="json")["service_types"] == ["electrical"]
    assert legacy.service_scale.value == "minor"

    with pytest.raises(ValidationError):
        MaintenanceLogCreateInput(vehicle_id="v", date="2026-09-01", odometer_at_service=10, service_types=[])


def test_incident_input_carries_new_fields() -> None:
    incident = IncidentCreateInput(
        vehicle_id="v", incident_type="damage", date="2026-09-10", severity="minor", description="d",
        incident_time="2026-09-10T14:30:00+00:00", location_area="Gate B", remarks="r", attachment_url="https://x/y.jpg",
    )
    dumped = incident.model_dump(mode="json")
    assert dumped["incident_time"].startswith("2026-09-10T14:30:00")
    assert (dumped["location_area"], dumped["remarks"], dumped["attachment_url"]) == ("Gate B", "r", "https://x/y.jpg")


# --- Foundation graph -----------------------------------------------------------------------


def _foundation(extraction_kwargs: dict, document_type: str, provided: dict | None = None):
    capture = _Capture()
    extractors = {
        "vehicle_doc": ("extract_vehicle", VehicleDocExtraction),
        "license": ("extract_license", LicenseExtraction),
        "supplier_doc": ("extract_supplier", SupplierDocExtraction),
    }
    key, model = extractors[document_type]
    creators = {"vehicle_doc": "create_vehicle", "license": "create_driver", "supplier_doc": "create_supplier"}
    deps = FoundationAgentDeps(
        **{key: lambda img, mime: model(**extraction_kwargs)},
        get_vehicles=lambda ctx: [],
        get_drivers=lambda ctx: [],
        get_suppliers=lambda ctx: [],
        **{creators[document_type]: capture},
    )
    state = get_compiled_foundation_graph(deps).invoke(
        {
            "token": _token(),
            "document_type": document_type,
            "image_bytes": b"jpeg",
            "mime_type": "image/jpeg",
            "provided_fields": provided or {},
        }
    )
    return state, capture


def test_foundation_vehicle_extracts_engine_chassis_and_maps_ownership() -> None:
    state, capture = _foundation(
        dict(plate_number="ABC-123", make="Toyota", model="Hilux", year=2022, vin="1HGCM82633A004352",
             engine_number=" ENG-9 ", chassis_number="CH-7", ownership_type="Leasing"),
        "vehicle_doc",
        provided={"fuel_type": "diesel"},
    )
    assert state["stage"] == "done"
    payload = capture.calls[0]
    assert (payload["engine_number"], payload["chassis_number"], payload["ownership_type"]) == ("ENG-9", "CH-7", "leasing")


def test_foundation_vehicle_provided_fields_override_and_bad_ownership_falls_back() -> None:
    state, capture = _foundation(
        dict(plate_number="ABC-123", make="Toyota", model="Hilux", year=2022, vin="1HGCM82633A004352",
             engine_number="OCR-ENG", ownership_type="???"),
        "vehicle_doc",
        provided={"fuel_type": "petrol", "engine_number": "TYPED-ENG", "ownership_type": "rent"},
    )
    payload = capture.calls[0]
    assert payload["engine_number"] == "TYPED-ENG"  # what the user typed beats OCR
    assert payload["ownership_type"] == "rent"

    _, capture2 = _foundation(
        dict(plate_number="ABC-124", make="Toyota", model="Hilux", year=2022, vin="1HGCM82633A004353",
             ownership_type="???"),
        "vehicle_doc",
        provided={"fuel_type": "petrol"},
    )
    assert capture2.calls[0]["ownership_type"] == "owner"


def test_foundation_license_carries_license_type_issue_date_status_and_no_address() -> None:
    state, capture = _foundation(
        dict(first_name="Sara", last_name="Khan", license_number="LIC-1", phone_number="03001234567",
             expiration_date=date(2035, 1, 1), license_type="HTV", license_issue_date=date(2020, 1, 1),
             license_current_status="valid"),
        "license",
    )
    assert state["stage"] == "done", state.get("halt_reason")
    payload = capture.calls[0]
    assert (payload["license_type"], payload["license_issue_date"], payload["license_current_status"]) == (
        "HTV", "2020-01-01", "valid",
    )
    assert "address" not in payload


def test_foundation_supplier_carries_address_and_normalised_category() -> None:
    state, capture = _foundation(
        dict(name="Speedy Tyres", address="12 Ring Rd", category="Tire Supplier"), "supplier_doc"
    )
    assert state["stage"] == "done"
    assert (capture.calls[0]["address"], capture.calls[0]["category"]) == ("12 Ring Rd", "tire_supplier")

    _, unknown = _foundation(dict(name="Odd Co", category="bakery"), "supplier_doc")
    assert unknown.calls[0]["category"] == "other"


# --- Fuel graph -------------------------------------------------------------------------------


def _fuel_deps(capture: _Capture) -> FuelAgentDeps:
    return FuelAgentDeps(
        extract_receipt=lambda img, mime: FuelReceiptExtraction(
            station_name="Shell Ring Road", receipt_date=date(2026, 9, 1), liters=40.0, total_cost=100.0,
            odometer=1200, plate_number="ABC-123", slip_id="SLIP-1", po_number="PO-1",
            payment_method="Fuel Card", card_used="**** 4242",
        ),
        get_vehicles=lambda ctx: [{"id": "v1", "plate_number": "ABC-123", "current_odometer": 1000}],
        create_fuel_log=capture,
    )


def test_fuel_receipt_flow_writes_slip_fields() -> None:
    capture = _Capture()
    state = get_compiled_fuel_graph(_fuel_deps(capture)).invoke(
        {"token": _token(), "image_bytes": b"jpeg", "mime_type": "image/jpeg"}
    )
    assert state["stage"] == "done", state.get("halt_reason")
    payload = capture.calls[0]
    assert payload["slip_id"] == "SLIP-1"
    assert payload["po_number"] == "PO-1"
    assert payload["payment_method"] == "fuel card"
    assert payload["card_used"] == "**** 4242"
    assert payload["fuel_station_name"] == "Shell Ring Road"


def test_fuel_fields_from_chat_override_receipt_values() -> None:
    capture = _Capture()
    state = get_compiled_fuel_graph(_fuel_deps(capture)).invoke(
        {
            "token": _token(),
            "image_bytes": b"jpeg",
            "mime_type": "image/jpeg",
            "fuel_fields": {"slip_id": "TYPED-9", "payment_method": "cash", "driver_id": "d1"},
        }
    )
    assert state["stage"] == "done"
    assert (capture.calls[0]["slip_id"], capture.calls[0]["payment_method"], capture.calls[0]["driver_id"]) == (
        "TYPED-9", "cash", "d1",
    )
    assert capture.calls[0]["po_number"] == "PO-1"  # untouched keys keep the OCR value


def test_fuel_fields_alone_create_a_text_only_log() -> None:
    capture = _Capture()
    state = get_compiled_fuel_graph(_fuel_deps(capture)).invoke(
        {
            "token": _token(),
            "fuel_fields": {
                "vehicle_id": "v1", "date": "2026-09-02", "odometer_reading": 1500, "liters_filled": "30",
                "price_per_liter": "2.5", "total_cost": "75", "slip_id": "S-77", "po_number": "PO-5",
            },
        }
    )
    assert state["stage"] == "done"
    assert (capture.calls[0]["slip_id"], capture.calls[0]["po_number"]) == ("S-77", "PO-5")


def test_incomplete_fuel_fields_halt_readably() -> None:
    capture = _Capture()
    state = get_compiled_fuel_graph(_fuel_deps(capture)).invoke({"token": _token(), "fuel_fields": {"slip_id": "S-1"}})
    assert state["stage"] == "halted"
    assert "fuel_fields" in state["halt_reason"]
    assert capture.calls == []


# --- Maintenance graph ------------------------------------------------------------------------


def _maintenance(extraction: WorkOrderExtraction, drivers: list[dict]):
    capture = _Capture()

    def create_log(context, data):
        capture.calls.append(data.model_dump(mode="json"))
        return {"id": "log-1", **capture.calls[-1]}

    deps = MaintenanceAgentDeps(
        extract_work_order=lambda img, mime, text=None: extraction,
        get_vehicles=lambda ctx: [{"id": "v1", "plate_number": "ABC-123", "current_odometer": 9000}],
        get_drivers=lambda ctx: drivers,
        get_inventory=lambda ctx: [],
        create_maintenance_log=create_log,
        create_mechanic_report=lambda ctx, log_id, data: {"id": "r1"},
    )
    state = get_compiled_maintenance_graph(deps).invoke(
        {"token": _token("mechanic"), "document_type": "work_order", "document_text": "typed note"}
    )
    return state, capture


def test_maintenance_extracts_many_services_scale_and_driver() -> None:
    state, capture = _maintenance(
        WorkOrderExtraction(
            issue_description="Full service", service_types=["oil_change", "Brake Service", "oil_change", "nonsense"],
            service_scale="Major", driver_name="omar farooq", vehicle_plate="ABC-123", odometer=9500,
        ),
        drivers=[{"id": "d9", "full_name": "Omar Farooq"}],
    )
    assert state["stage"] == "done", state.get("halt_reason")
    payload = capture.calls[0]
    assert payload["service_types"] == ["oil_change", "brake_service"]
    assert payload["service_scale"] == "major"
    assert payload["driver_id"] == "d9"


def test_maintenance_legacy_service_type_and_unknown_driver_still_file() -> None:
    state, capture = _maintenance(
        WorkOrderExtraction(
            issue_description="Wiring", service_type="electrical", driver_name="Nobody Known",
            vehicle_plate="ABC-123", odometer=9500,
        ),
        drivers=[{"id": "d9", "full_name": "Omar Farooq"}],
    )
    assert state["stage"] == "done"
    payload = capture.calls[0]
    assert payload["service_types"] == ["electrical"]
    assert payload["service_scale"] == "minor"
    assert payload["driver_id"] is None


def test_maintenance_with_no_recognisable_service_files_as_other() -> None:
    state, capture = _maintenance(
        WorkOrderExtraction(issue_description="?", vehicle_plate="ABC-123", odometer=9500), drivers=[]
    )
    assert state["stage"] == "done"
    assert capture.calls[0]["service_types"] == ["other"]


# --- Accountability graph -------------------------------------------------------------------


def test_incident_extraction_flows_time_area_remarks_attachment() -> None:
    capture = _Capture()
    deps = AccountabilityAgentDeps(
        extract_incident=lambda img, mime, text=None: IncidentExtraction(
            incident_time=datetime(2026, 9, 10, 14, 30, tzinfo=timezone.utc), location="Main road",
            location_area=" Warehouse gate B ", remarks="Reversed too fast", attachment_url="https://x/y.jpg",
            severity="minor", incident_type="damage", vehicle_plate="ABC-123", driver_name="Faisal Rana",
            damage_description="Scraped gate",
        ),
        get_vehicles=lambda ctx: [{"id": "v1", "plate_number": "ABC-123"}],
        get_drivers=lambda ctx: [{"id": "d1", "full_name": "Faisal Rana", "user_id": "u"}],
        create_incident=capture,
    )
    state = get_compiled_accountability_graph(deps).invoke(
        {"token": _token("admin"), "document_type": "incident_report", "document_text": "statement"}
    )
    assert state["stage"] == "done", state.get("halt_reason")
    payload = capture.calls[0]
    assert payload["date"] == "2026-09-10"  # derived from incident_time
    assert payload["incident_time"].startswith("2026-09-10T14:30:00")
    assert payload["location_description"] == "Main road"
    assert payload["location_area"] == "Warehouse gate B"
    assert (payload["remarks"], payload["attachment_url"]) == ("Reversed too fast", "https://x/y.jpg")
    assert payload["driver_id"] == "d1"


# --- LLM-facing tool schemas ----------------------------------------------------------------


def test_tool_descriptions_name_the_new_keys() -> None:
    assert all(k in FoundationToolInput.__doc__ for k in ("engine_number", "chassis_number", "ownership_type", "license_type", "category"))
    assert "address" in FoundationToolInput.__doc__
    assert all(k in FuelToolInput.__doc__ for k in ("slip_id", "po_number", "payment_method", "card_used", "fuel_station_name", "cost_per_km"))
    assert all(k in MaintenanceToolInput.__doc__ for k in ("service_types", "service_scale", "driver_name"))
    assert all(k in AccountabilityToolInput.__doc__ for k in ("incident_time", "location_area", "remarks", "attachment_url"))
    assert all(k in AssignmentToolInput.__doc__ for k in ("vehicle_make", "vehicle_model"))


def test_fuel_fields_is_a_structural_key_and_counts_as_a_write() -> None:
    assert FuelToolInput(fuel_fields={"slip_id": "S1"}).fuel_fields == {"slip_id": "S1"}
    assert _is_read_only_call("fuel", {"fuel_fields": {"slip_id": "S1"}}) is False
    assert _is_read_only_call("fuel", {"query_entity": "fuel_logs"}) is True
