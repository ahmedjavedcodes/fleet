"""Coverage for the expand_fleet_operational_fields migration: new columns
round-trip through POST/PUT, and GET responses carry the joined vehicle/driver
display fields."""

import uuid
from datetime import date, datetime, timezone

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.models.enums import UserRole
from app.models.organization import Organization
from tests.conftest import auth_headers, make_assignment, make_driver, make_maintenance_log, make_user, make_vehicle


def _admin(db_session: Session, organization: Organization):
    return make_user(db_session, organization, role=UserRole.admin)


# --- Foundation -----------------------------------------------------------------


def test_vehicle_new_fields_and_added_by(client: TestClient, db_session: Session, organization: Organization) -> None:
    admin = _admin(db_session, organization)
    response = client.post(
        "/api/v1/vehicles",
        json={
            "plate_number": "ABC-123",
            "make": "Toyota",
            "model": "Hilux",
            "year": 2022,
            "vin": uuid.uuid4().hex[:17].upper(),
            "fuel_type": "diesel",
            "engine_number": "ENG-991",
            "chassis_number": "CH-552",
            "ownership_type": "leasing",
            # Server-side attribution: a client-supplied added_by must be ignored.
            "added_by": str(uuid.uuid4()),
        },
        headers=auth_headers(admin),
    )
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["engine_number"] == "ENG-991"
    assert body["chassis_number"] == "CH-552"
    assert body["ownership_type"] == "leasing"
    assert body["added_by"] == str(admin.id)


def test_vehicle_ownership_defaults_to_owner_and_rejects_bad_value(
    client: TestClient, db_session: Session, organization: Organization
) -> None:
    admin = _admin(db_session, organization)
    payload = {
        "plate_number": "DEF-456",
        "make": "Isuzu",
        "model": "D-Max",
        "year": 2021,
        "vin": uuid.uuid4().hex[:17].upper(),
        "fuel_type": "diesel",
    }
    created = client.post("/api/v1/vehicles", json=payload, headers=auth_headers(admin))
    assert created.json()["ownership_type"] == "owner"

    bad = client.post(
        "/api/v1/vehicles",
        json={**payload, "plate_number": "GHI-789", "vin": uuid.uuid4().hex[:17].upper(), "ownership_type": "stolen"},
        headers=auth_headers(admin),
    )
    assert bad.status_code == 422


def test_driver_license_fields_roundtrip(client: TestClient, db_session: Session, organization: Organization) -> None:
    admin = _admin(db_session, organization)
    response = client.post(
        "/api/v1/drivers",
        json={
            "full_name": "Sara Khan",
            "license_number": "LIC-1",
            "license_expiry": "2030-01-01",
            "phone": "555-0101",
            "license_type": "heavy_vehicle",
            "license_issue_date": "2020-01-01",
            "license_current_status": "valid",
        },
        headers=auth_headers(admin),
    )
    assert response.status_code == 201, response.text
    body = response.json()
    assert (body["license_type"], body["license_issue_date"], body["license_current_status"]) == (
        "heavy_vehicle",
        "2020-01-01",
        "valid",
    )
    assert "address" not in body

    updated = client.put(
        f"/api/v1/drivers/{body['id']}", json={"license_current_status": "expired"}, headers=auth_headers(admin)
    )
    assert updated.json()["license_current_status"] == "expired"


def test_supplier_address_category_and_filter(client: TestClient, db_session: Session, organization: Organization) -> None:
    admin = _admin(db_session, organization)
    headers = auth_headers(admin)
    client.post(
        "/api/v1/suppliers",
        json={"name": "Speedy Tyres", "address": "12 Ring Rd", "category": "tire_supplier"},
        headers=headers,
    )
    client.post("/api/v1/suppliers", json={"name": "Generic Co"}, headers=headers)

    listed = client.get("/api/v1/suppliers", headers=headers).json()
    by_name = {s["name"]: s for s in listed}
    assert by_name["Speedy Tyres"]["address"] == "12 Ring Rd"
    assert by_name["Speedy Tyres"]["category"] == "tire_supplier"
    assert by_name["Generic Co"]["category"] == "other"

    filtered = client.get("/api/v1/suppliers?category=tire_supplier", headers=headers).json()
    assert [s["name"] for s in filtered] == ["Speedy Tyres"]


# --- Custody & operations -------------------------------------------------------------


def test_assignment_history_includes_vehicle_make_and_model(
    client: TestClient, db_session: Session, organization: Organization
) -> None:
    admin = _admin(db_session, organization)
    vehicle = make_vehicle(db_session, organization, make="Ford", model="Ranger", plate_number="ASG-1")
    driver = make_driver(db_session, organization, full_name="Omar Farooq")
    make_assignment(db_session, organization, vehicle, driver)

    by_driver = client.get(f"/api/v1/drivers/{driver.id}/assignments", headers=auth_headers(admin)).json()
    entry = by_driver["history"][0]
    assert (entry["vehicle_make"], entry["vehicle_model"], entry["vehicle_plate"]) == ("Ford", "Ranger", "ASG-1")
    assert entry["driver_name"] == "Omar Farooq"
    assert by_driver["current_assignment"]["vehicle_make"] == "Ford"

    by_vehicle = client.get(f"/api/v1/vehicles/{vehicle.id}/assignments", headers=auth_headers(admin)).json()
    assert by_vehicle[0]["vehicle_make"] == "Ford"
    assert by_vehicle[0]["vehicle_model"] == "Ranger"


def test_trip_response_includes_vehicle_and_driver_names(
    client: TestClient, db_session: Session, organization: Organization
) -> None:
    admin = _admin(db_session, organization)
    vehicle = make_vehicle(db_session, organization, make="Nissan", model="Navara", plate_number="TRP-9")
    driver = make_driver(db_session, organization, full_name="Lina Ahmed")
    payload = {
        "driver_id": str(driver.id),
        "vehicle_id": str(vehicle.id),
        "start_time": datetime(2026, 9, 1, 8, tzinfo=timezone.utc).isoformat(),
        "end_time": datetime(2026, 9, 1, 12, tzinfo=timezone.utc).isoformat(),
        "start_odometer": 1000,
        "end_odometer": 1100,
    }
    created = client.post("/api/v1/trips", json=payload, headers=auth_headers(admin))
    assert created.status_code == 201, created.text
    trip = created.json()
    assert trip["driver_id"] == str(driver.id)
    assert trip["start_odometer"] == 1000 and trip["end_odometer"] == 1100
    assert (trip["vehicle_name"], trip["vehicle_plate"], trip["driver_name"]) == ("Nissan Navara", "TRP-9", "Lina Ahmed")

    listed = client.get("/api/v1/trips", headers=auth_headers(admin)).json()
    assert listed[0]["driver_name"] == "Lina Ahmed"
    assert listed[0]["vehicle_plate"] == "TRP-9"


def test_fuel_slip_fields_single_view_and_joined_names(
    client: TestClient, db_session: Session, organization: Organization
) -> None:
    admin = _admin(db_session, organization)
    vehicle = make_vehicle(db_session, organization, make="Honda", model="Civic", plate_number="FUL-1")
    driver = make_driver(db_session, organization, full_name="Zain Malik")
    headers = auth_headers(admin)

    def _log(day: str, odometer: int, **extra: object) -> dict:
        response = client.post(
            "/api/v1/fuel",
            json={
                "vehicle_id": str(vehicle.id),
                "driver_id": str(driver.id),
                "date": day,
                "odometer_reading": odometer,
                "liters_filled": "40.00",
                "price_per_liter": "2.50",
                "total_cost": "100.00",
                **extra,
            },
            headers=headers,
        )
        assert response.status_code == 201, response.text
        return response.json()

    first = _log("2026-08-01", 1000)
    assert first["cost_per_km"] is None  # no prior log to measure against

    second = _log(
        "2026-08-10",
        1200,
        po_number="PO-77",
        payment_method="fuel_card",
        card_used="**** 4242",
        fuel_station_name="Shell Ring Road",
        slip_id="SLIP-0001",
    )
    assert second["cost_per_km"] == "0.5000"  # 100.00 / 200 km

    detail = client.get(f"/api/v1/fuel/{second['id']}", headers=headers).json()
    assert detail["po_number"] == "PO-77"
    assert detail["payment_method"] == "fuel_card"
    assert detail["card_used"] == "**** 4242"
    assert detail["fuel_station_name"] == "Shell Ring Road"
    assert detail["slip_id"] == "SLIP-0001"
    assert detail["cost_per_km"] == "0.5000"
    assert (detail["vehicle_name"], detail["vehicle_plate"], detail["driver_name"]) == ("Honda Civic", "FUL-1", "Zain Malik")

    listed = client.get("/api/v1/fuel", headers=headers).json()
    assert {row["driver_name"] for row in listed} == {"Zain Malik"}

    edited = client.put(f"/api/v1/fuel/{second['id']}", json={"slip_id": "SLIP-0002"}, headers=headers).json()
    assert edited["slip_id"] == "SLIP-0002"


def test_fuel_summary_includes_names_and_dates(
    client: TestClient, db_session: Session, organization: Organization
) -> None:
    admin = _admin(db_session, organization)
    vehicle = make_vehicle(db_session, organization, make="Kia", model="Sportage", plate_number="SUM-1")
    driver = make_driver(db_session, organization, full_name="Hina Baig")
    headers = auth_headers(admin)
    client.post(
        "/api/v1/fuel",
        json={
            "vehicle_id": str(vehicle.id),
            "driver_id": str(driver.id),
            "date": "2026-08-05",
            "odometer_reading": 500,
            "liters_filled": "30.00",
            "price_per_liter": "2.00",
            "total_cost": "60.00",
        },
        headers=headers,
    )
    summary = client.get("/api/v1/fuel/summary?month=2026-08", headers=headers).json()
    assert summary["period_start"] == "2026-08-01"
    assert summary["period_end"] == "2026-08-31"
    assert summary["generated_at"]
    row = summary["by_vehicle"][0]
    assert row["plate_number"] == "SUM-1"
    assert row["vehicle_name"] == "Kia Sportage"
    assert row["driver_names"] == ["Hina Baig"]
    assert row["first_fill_date"] == "2026-08-05" and row["last_fill_date"] == "2026-08-05"
    assert row["fill_count"] == 1


# --- Maintenance & accountability ------------------------------------------------------


def test_maintenance_multiple_services_scale_and_driver(
    client: TestClient, db_session: Session, organization: Organization
) -> None:
    admin = _admin(db_session, organization)
    vehicle = make_vehicle(db_session, organization, make="Suzuki", model="Cultus", plate_number="MNT-1")
    driver = make_driver(db_session, organization, full_name="Bilal Shah")
    headers = auth_headers(admin)

    created = client.post(
        "/api/v1/maintenance",
        json={
            "vehicle_id": str(vehicle.id),
            "date": "2026-07-01",
            "odometer_at_service": 5000,
            "service_types": ["oil_change", "brake_service", "oil_change"],
            "service_scale": "major",
            "driver_id": str(driver.id),
        },
        headers=headers,
    )
    assert created.status_code == 201, created.text
    log = created.json()
    assert log["service_types"] == ["oil_change", "brake_service"]  # de-duplicated, order kept
    assert log["service_type"] == "oil_change"  # primary
    assert log["service_scale"] == "major"
    assert (log["driver_id"], log["driver_name"], log["vehicle_plate"]) == (str(driver.id), "Bilal Shah", "MNT-1")

    # Filtering by ANY service on the visit finds it.
    by_second = client.get("/api/v1/maintenance?service_type=brake_service", headers=headers).json()
    assert [row["id"] for row in by_second] == [log["id"]]

    replaced = client.put(
        f"/api/v1/maintenance/{log['id']}", json={"service_types": ["tire_rotation"]}, headers=headers
    ).json()
    assert replaced["service_types"] == ["tire_rotation"]
    assert replaced["service_type"] == "tire_rotation"
    assert client.get("/api/v1/maintenance?service_type=brake_service", headers=headers).json() == []


def test_maintenance_legacy_single_service_type_still_accepted(
    client: TestClient, db_session: Session, organization: Organization
) -> None:
    admin = _admin(db_session, organization)
    vehicle = make_vehicle(db_session, organization, plate_number="MNT-2")
    response = client.post(
        "/api/v1/maintenance",
        json={"vehicle_id": str(vehicle.id), "date": "2026-07-01", "odometer_at_service": 10, "service_type": "electrical"},
        headers=auth_headers(admin),
    )
    assert response.status_code == 201, response.text
    assert response.json()["service_types"] == ["electrical"]
    assert response.json()["service_scale"] == "minor"


def test_maintenance_requires_at_least_one_service(
    client: TestClient, db_session: Session, organization: Organization
) -> None:
    admin = _admin(db_session, organization)
    vehicle = make_vehicle(db_session, organization, plate_number="MNT-3")
    response = client.post(
        "/api/v1/maintenance",
        json={"vehicle_id": str(vehicle.id), "date": "2026-07-01", "odometer_at_service": 10, "service_types": []},
        headers=auth_headers(admin),
    )
    assert response.status_code == 422


def test_overdue_matches_every_service_on_a_multi_service_visit(
    client: TestClient, db_session: Session, organization: Organization
) -> None:
    admin = _admin(db_session, organization)
    vehicle = make_vehicle(
        db_session, organization, plate_number="OVD-1", make="Mazda", model="3", current_odometer=9000, service_interval_km=1000
    )
    driver = make_driver(db_session, organization, full_name="Nadia Iqbal")
    headers = auth_headers(admin)
    client.post(
        "/api/v1/maintenance",
        json={
            "vehicle_id": str(vehicle.id),
            "date": "2026-01-01",
            "odometer_at_service": 5000,
            "service_types": ["oil_change", "brake_service"],
            "driver_id": str(driver.id),
        },
        headers=headers,
    )
    overdue = client.get("/api/v1/maintenance/overdue", headers=headers).json()
    assert {item["service_type"] for item in overdue} == {"oil_change", "brake_service"}
    assert all(item["driver_name"] == "Nadia Iqbal" for item in overdue)
    assert all(item["vehicle_name"] == "Mazda 3" and item["last_service_date"] == "2026-01-01" for item in overdue)


def test_maintenance_rejects_unknown_driver(client: TestClient, db_session: Session, organization: Organization) -> None:
    admin = _admin(db_session, organization)
    vehicle = make_vehicle(db_session, organization, plate_number="MNT-4")
    response = client.post(
        "/api/v1/maintenance",
        json={
            "vehicle_id": str(vehicle.id),
            "date": "2026-07-01",
            "odometer_at_service": 10,
            "service_types": ["other"],
            "driver_id": str(uuid.uuid4()),
        },
        headers=auth_headers(admin),
    )
    assert response.status_code == 404


def test_incident_new_fields_and_joined_names(client: TestClient, db_session: Session, organization: Organization) -> None:
    admin = _admin(db_session, organization)
    vehicle = make_vehicle(db_session, organization, make="Hino", model="300", plate_number="INC-1")
    driver = make_driver(db_session, organization, full_name="Faisal Rana")
    headers = auth_headers(admin)
    response = client.post(
        "/api/v1/incidents",
        json={
            "driver_id": str(driver.id),
            "vehicle_id": str(vehicle.id),
            "incident_type": "damage",
            "incident_time": "2026-09-10T14:30:00+00:00",
            "severity": "minor",
            "description": "Scraped the gate",
            "location_area": "Warehouse gate B",
            "remarks": "Driver reversed too fast",
            "attachment_url": "https://files.example.com/inc-1.jpg",
        },
        headers=headers,
    )
    assert response.status_code == 201, response.text
    incident = response.json()
    assert incident["date"] == "2026-09-10"  # derived from incident_time
    assert datetime.fromisoformat(incident["incident_time"]) == datetime(2026, 9, 10, 14, 30, tzinfo=timezone.utc)
    assert incident["location_area"] == "Warehouse gate B"
    assert incident["remarks"] == "Driver reversed too fast"
    assert incident["attachment_url"] == "https://files.example.com/inc-1.jpg"
    assert (incident["driver_name"], incident["vehicle_plate"]) == ("Faisal Rana", "INC-1")

    timeline = client.get(f"/api/v1/vehicles/{vehicle.id}/timeline", headers=headers).json()
    summary = timeline[0]["summary"]
    assert summary["driver_name"] == "Faisal Rana"
    assert summary["vehicle_plate"] == "INC-1"
    assert summary["location_area"] == "Warehouse gate B"


def test_incident_requires_date_or_incident_time(
    client: TestClient, db_session: Session, organization: Organization
) -> None:
    admin = _admin(db_session, organization)
    vehicle = make_vehicle(db_session, organization, plate_number="INC-2")
    base = {"vehicle_id": str(vehicle.id), "incident_type": "near_miss", "severity": "minor", "description": "x"}
    assert client.post("/api/v1/incidents", json=base, headers=auth_headers(admin)).status_code == 422
    ok = client.post("/api/v1/incidents", json={**base, "date": "2026-09-01"}, headers=auth_headers(admin))
    assert ok.status_code == 201
    assert ok.json()["incident_time"] is None


def test_maintenance_log_factory_creates_service_row(db_session: Session, organization: Organization) -> None:
    """Direct-constructed logs (fixtures, seed scripts) still get their service row."""
    vehicle = make_vehicle(db_session, organization, plate_number="FAC-1")
    log = make_maintenance_log(db_session, organization, vehicle)
    assert log.service_types == [log.service_type]
    assert date(2026, 6, 1) == log.date
