import uuid
from datetime import date, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.models.enums import UserRole
from app.models.organization import Organization
from tests.conftest import auth_headers, make_driver, make_user, make_vehicle

BASE_DATE = date(2026, 6, 1)


@pytest.fixture()
def admin(db_session: Session, organization: Organization):
    return make_user(db_session, organization, role=UserRole.admin)


@pytest.fixture()
def vehicle(db_session: Session, organization: Organization):
    return make_vehicle(db_session, organization)


@pytest.fixture()
def driver_setup(db_session: Session, organization: Organization):
    """Returns (driver_user, driver_profile) for a driver with app login access."""
    driver_user = make_user(db_session, organization, role=UserRole.driver)
    driver_profile = make_driver(db_session, organization, user=driver_user)
    return driver_user, driver_profile


def _fuel_payload(vehicle_id, **overrides) -> dict:
    payload = {
        "vehicle_id": str(vehicle_id),
        "date": str(BASE_DATE),
        "odometer_reading": 1000,
        "liters_filled": "50.00",
        "price_per_liter": "20.00",
        "total_cost": "1000.00",
        "notes": None,
    }
    payload.update(overrides)
    return payload


# --- Core computation behavior ---------------------------------------------


def test_first_fuel_log_has_null_cost_per_km(client: TestClient, admin, vehicle) -> None:
    response = client.post("/api/v1/fuel", json=_fuel_payload(vehicle.id), headers=auth_headers(admin))
    assert response.status_code == 201
    body = response.json()
    assert body["cost_per_km"] is None
    assert body["is_anomalous"] is False


def test_cost_per_km_computed_correctly(client: TestClient, admin, vehicle) -> None:
    client.post("/api/v1/fuel", json=_fuel_payload(vehicle.id, odometer_reading=1000), headers=auth_headers(admin))
    response = client.post(
        "/api/v1/fuel",
        json=_fuel_payload(vehicle.id, date=str(BASE_DATE + timedelta(days=10)), odometer_reading=1100, total_cost="1800.00"),
        headers=auth_headers(admin),
    )
    assert response.status_code == 201
    assert response.json()["cost_per_km"] == "18.0000"


def test_odometer_not_increased_raises_validation_error(client: TestClient, admin, vehicle) -> None:
    client.post("/api/v1/fuel", json=_fuel_payload(vehicle.id, odometer_reading=1000), headers=auth_headers(admin))
    response = client.post(
        "/api/v1/fuel",
        json=_fuel_payload(vehicle.id, date=str(BASE_DATE + timedelta(days=10)), odometer_reading=1000),
        headers=auth_headers(admin),
    )
    assert response.status_code == 400


def test_vehicle_odometer_updated_as_side_effect(client: TestClient, admin, vehicle, db_session: Session) -> None:
    client.post("/api/v1/fuel", json=_fuel_payload(vehicle.id, odometer_reading=1500), headers=auth_headers(admin))
    get_resp = client.get(f"/api/v1/vehicles/{vehicle.id}", headers=auth_headers(admin))
    assert get_resp.json()["current_odometer"] == 1500


def test_vehicle_odometer_not_decreased(client: TestClient, admin, vehicle) -> None:
    client.post("/api/v1/fuel", json=_fuel_payload(vehicle.id, odometer_reading=2000), headers=auth_headers(admin))
    client.post(
        "/api/v1/fuel",
        json=_fuel_payload(vehicle.id, date=str(BASE_DATE - timedelta(days=30)), odometer_reading=500),
        headers=auth_headers(admin),
    )
    get_resp = client.get(f"/api/v1/vehicles/{vehicle.id}", headers=auth_headers(admin))
    assert get_resp.json()["current_odometer"] == 2000


def test_vehicle_not_found_returns_404(client: TestClient, admin) -> None:
    response = client.post("/api/v1/fuel", json=_fuel_payload(uuid.uuid4()), headers=auth_headers(admin))
    assert response.status_code == 404


# --- Anomaly detection -------------------------------------------------------


def _seed_stable_history(client: TestClient, admin, vehicle) -> None:
    client.post("/api/v1/fuel", json=_fuel_payload(vehicle.id, date=str(BASE_DATE - timedelta(days=80)), odometer_reading=1000), headers=auth_headers(admin))
    client.post("/api/v1/fuel", json=_fuel_payload(vehicle.id, date=str(BASE_DATE - timedelta(days=80 - 25)), odometer_reading=1100, total_cost="1800.00"), headers=auth_headers(admin))
    client.post("/api/v1/fuel", json=_fuel_payload(vehicle.id, date=str(BASE_DATE - timedelta(days=80 - 50)), odometer_reading=1200, total_cost="1800.00"), headers=auth_headers(admin))
    client.post("/api/v1/fuel", json=_fuel_payload(vehicle.id, date=str(BASE_DATE - timedelta(days=80 - 75)), odometer_reading=1300, total_cost="1800.00"), headers=auth_headers(admin))


def test_anomaly_flagged_over_20_percent_deviation(client: TestClient, admin, vehicle) -> None:
    _seed_stable_history(client, admin, vehicle)
    response = client.post(
        "/api/v1/fuel",
        json=_fuel_payload(vehicle.id, date=str(BASE_DATE), odometer_reading=1400, total_cost="2600.00"),
        headers=auth_headers(admin),
    )
    assert response.status_code == 201
    assert response.json()["is_anomalous"] is True


def test_anomaly_not_flagged_within_threshold(client: TestClient, admin, vehicle) -> None:
    _seed_stable_history(client, admin, vehicle)
    response = client.post(
        "/api/v1/fuel",
        json=_fuel_payload(vehicle.id, date=str(BASE_DATE), odometer_reading=1400, total_cost="1900.00"),
        headers=auth_headers(admin),
    )
    assert response.status_code == 201
    assert response.json()["is_anomalous"] is False


def test_anomaly_not_flagged_with_insufficient_history(client: TestClient, admin, vehicle) -> None:
    client.post("/api/v1/fuel", json=_fuel_payload(vehicle.id, date=str(BASE_DATE - timedelta(days=60)), odometer_reading=1000), headers=auth_headers(admin))
    client.post("/api/v1/fuel", json=_fuel_payload(vehicle.id, date=str(BASE_DATE - timedelta(days=40)), odometer_reading=1100, total_cost="1800.00"), headers=auth_headers(admin))
    # Only one prior non-null cost_per_km data point exists -- below MIN_ROLLING_HISTORY.
    response = client.post(
        "/api/v1/fuel",
        json=_fuel_payload(vehicle.id, date=str(BASE_DATE), odometer_reading=1200, total_cost="5000.00"),
        headers=auth_headers(admin),
    )
    assert response.status_code == 201
    assert response.json()["is_anomalous"] is False


# --- Update behavior ----------------------------------------------------------


def test_update_fuel_log_recalculates_cost_per_km(client: TestClient, admin, vehicle) -> None:
    client.post("/api/v1/fuel", json=_fuel_payload(vehicle.id, odometer_reading=1000), headers=auth_headers(admin))
    second = client.post(
        "/api/v1/fuel",
        json=_fuel_payload(vehicle.id, date=str(BASE_DATE + timedelta(days=10)), odometer_reading=1100, total_cost="1800.00"),
        headers=auth_headers(admin),
    ).json()
    assert second["cost_per_km"] == "18.0000"

    updated = client.put(
        f"/api/v1/fuel/{second['id']}", json={"odometer_reading": 1200}, headers=auth_headers(admin)
    )
    assert updated.status_code == 200
    assert updated.json()["cost_per_km"] == "9.0000"  # 1800 / (1200-1000)


def test_update_does_not_cascade_to_next_log(client: TestClient, admin, vehicle) -> None:
    log1 = client.post("/api/v1/fuel", json=_fuel_payload(vehicle.id, odometer_reading=1000), headers=auth_headers(admin)).json()
    log2 = client.post(
        "/api/v1/fuel",
        json=_fuel_payload(vehicle.id, date=str(BASE_DATE + timedelta(days=10)), odometer_reading=1100, total_cost="1800.00"),
        headers=auth_headers(admin),
    ).json()
    log3 = client.post(
        "/api/v1/fuel",
        json=_fuel_payload(vehicle.id, date=str(BASE_DATE + timedelta(days=20)), odometer_reading=1200, total_cost="1800.00"),
        headers=auth_headers(admin),
    ).json()
    assert log3["cost_per_km"] == "18.0000"

    client.put(f"/api/v1/fuel/{log2['id']}", json={"odometer_reading": 1050}, headers=auth_headers(admin))

    log3_after = client.get(f"/api/v1/fuel/{log3['id']}", headers=auth_headers(admin)).json()
    assert log3_after["cost_per_km"] == "18.0000"  # unchanged despite log2's edit
    _ = log1


def test_update_omitting_delta_fields_keeps_same_cost_per_km(client: TestClient, admin, vehicle) -> None:
    client.post("/api/v1/fuel", json=_fuel_payload(vehicle.id, odometer_reading=1000), headers=auth_headers(admin))
    second = client.post(
        "/api/v1/fuel",
        json=_fuel_payload(vehicle.id, date=str(BASE_DATE + timedelta(days=10)), odometer_reading=1100, total_cost="1800.00"),
        headers=auth_headers(admin),
    ).json()

    updated = client.put(f"/api/v1/fuel/{second['id']}", json={"notes": "corrected station name"}, headers=auth_headers(admin))
    assert updated.json()["cost_per_km"] == second["cost_per_km"]


# --- Receipts ------------------------------------------------------------------


def test_receipt_upload_sets_pending_status(client: TestClient, admin, vehicle) -> None:
    log = client.post("/api/v1/fuel", json=_fuel_payload(vehicle.id), headers=auth_headers(admin)).json()
    response = client.post(
        f"/api/v1/fuel/{log['id']}/receipt",
        files={"file": ("receipt.pdf", b"%PDF-1.4 fake receipt content", "application/pdf")},
        headers=auth_headers(admin),
    )
    assert response.status_code == 201
    body = response.json()
    assert body["upload_status"] == "pending"
    assert body["parsed_data"] is None


def test_receipt_duplicate_upload_rejected(client: TestClient, admin, vehicle) -> None:
    log = client.post("/api/v1/fuel", json=_fuel_payload(vehicle.id), headers=auth_headers(admin)).json()
    files = {"file": ("receipt.pdf", b"%PDF-1.4 fake receipt content", "application/pdf")}
    first = client.post(f"/api/v1/fuel/{log['id']}/receipt", files=files, headers=auth_headers(admin))
    assert first.status_code == 201
    second = client.post(f"/api/v1/fuel/{log['id']}/receipt", files=files, headers=auth_headers(admin))
    assert second.status_code == 409


def test_receipt_unsupported_file_type_rejected(client: TestClient, admin, vehicle) -> None:
    log = client.post("/api/v1/fuel", json=_fuel_payload(vehicle.id), headers=auth_headers(admin)).json()
    response = client.post(
        f"/api/v1/fuel/{log['id']}/receipt",
        files={"file": ("notes.txt", b"hello", "text/plain")},
        headers=auth_headers(admin),
    )
    assert response.status_code == 400


def test_receipt_empty_file_rejected(client: TestClient, admin, vehicle) -> None:
    log = client.post("/api/v1/fuel", json=_fuel_payload(vehicle.id), headers=auth_headers(admin)).json()
    response = client.post(
        f"/api/v1/fuel/{log['id']}/receipt",
        files={"file": ("receipt.pdf", b"", "application/pdf")},
        headers=auth_headers(admin),
    )
    assert response.status_code == 400


# --- Monthly summary ------------------------------------------------------------


def test_monthly_summary_matches_manual_aggregation(client: TestClient, admin, vehicle) -> None:
    client.post("/api/v1/fuel", json=_fuel_payload(vehicle.id, date="2026-06-05", odometer_reading=1000, liters_filled="40.00", total_cost="1000.00"), headers=auth_headers(admin))
    client.post("/api/v1/fuel", json=_fuel_payload(vehicle.id, date="2026-06-15", odometer_reading=1100, liters_filled="60.00", total_cost="1800.00"), headers=auth_headers(admin))
    # Outside the target month -- must be excluded.
    client.post("/api/v1/fuel", json=_fuel_payload(vehicle.id, date="2026-07-05", odometer_reading=1200, liters_filled="45.00", total_cost="900.00"), headers=auth_headers(admin))

    response = client.get("/api/v1/fuel/summary?month=2026-06", headers=auth_headers(admin))
    assert response.status_code == 200
    body = response.json()
    assert body["total_cost"] == "2800.00"
    assert body["total_liters"] == "100.00"
    assert body["avg_cost_per_km"] == "18.0000"  # only the second log has a non-null cost_per_km
    assert len(body["by_vehicle"]) == 1
    assert body["by_vehicle"][0]["vehicle_id"] == str(vehicle.id)
    assert body["by_vehicle"][0]["total_cost"] == "2800.00"
    assert body["by_vehicle"][0]["total_liters"] == "100.00"


# --- Filtering & org scoping ------------------------------------------------------


def test_list_filtered_by_vehicle_and_date_range(client: TestClient, admin, vehicle, db_session: Session, organization: Organization) -> None:
    other_vehicle = make_vehicle(db_session, organization)
    client.post("/api/v1/fuel", json=_fuel_payload(vehicle.id, date="2026-06-05", odometer_reading=1000), headers=auth_headers(admin))
    client.post("/api/v1/fuel", json=_fuel_payload(vehicle.id, date="2026-07-05", odometer_reading=1100), headers=auth_headers(admin))
    client.post("/api/v1/fuel", json=_fuel_payload(other_vehicle.id, date="2026-06-05", odometer_reading=500), headers=auth_headers(admin))

    response = client.get(
        f"/api/v1/fuel?vehicle_id={vehicle.id}&date_from=2026-06-01&date_to=2026-06-30", headers=auth_headers(admin)
    )
    assert response.status_code == 200
    results = response.json()
    assert len(results) == 1
    assert results[0]["vehicle_id"] == str(vehicle.id)


def test_org_scoping(client: TestClient, admin, vehicle, db_session: Session) -> None:
    client.post("/api/v1/fuel", json=_fuel_payload(vehicle.id), headers=auth_headers(admin))

    other_org = Organization(id=uuid.uuid4(), name="Other Co", slug=f"other-{uuid.uuid4().hex[:8]}")
    db_session.add(other_org)
    db_session.commit()
    other_admin = make_user(db_session, other_org, role=UserRole.admin)

    list_resp = client.get("/api/v1/fuel", headers=auth_headers(other_admin))
    assert list_resp.json() == []
    summary_resp = client.get(f"/api/v1/fuel/summary?month={BASE_DATE.strftime('%Y-%m')}", headers=auth_headers(other_admin))
    assert summary_resp.json()["total_cost"] == "0"


# --- GET /fuel listing: all-org fetch, vehicle_id isolation, pagination, tenant isolation ---


def test_list_all_organization_logs_returns_200(client: TestClient, admin, vehicle, db_session: Session, organization: Organization) -> None:
    other_vehicle = make_vehicle(db_session, organization)
    client.post("/api/v1/fuel", json=_fuel_payload(vehicle.id, odometer_reading=1000), headers=auth_headers(admin))
    client.post("/api/v1/fuel", json=_fuel_payload(other_vehicle.id, odometer_reading=500), headers=auth_headers(admin))

    response = client.get("/api/v1/fuel", headers=auth_headers(admin))
    assert response.status_code == 200
    results = response.json()
    assert len(results) == 2
    assert {r["vehicle_id"] for r in results} == {str(vehicle.id), str(other_vehicle.id)}


def test_list_filtering_by_vehicle_id_isolates_correct_logs(client: TestClient, admin, vehicle, db_session: Session, organization: Organization) -> None:
    other_vehicle = make_vehicle(db_session, organization)
    client.post("/api/v1/fuel", json=_fuel_payload(vehicle.id, odometer_reading=1000), headers=auth_headers(admin))
    client.post("/api/v1/fuel", json=_fuel_payload(vehicle.id, date=str(BASE_DATE + timedelta(days=10)), odometer_reading=1100), headers=auth_headers(admin))
    client.post("/api/v1/fuel", json=_fuel_payload(other_vehicle.id, odometer_reading=500), headers=auth_headers(admin))

    response = client.get(f"/api/v1/fuel?vehicle_id={vehicle.id}", headers=auth_headers(admin))
    assert response.status_code == 200
    results = response.json()
    assert len(results) == 2
    assert all(r["vehicle_id"] == str(vehicle.id) for r in results)


def test_list_cross_tenant_isolation(client: TestClient, admin, vehicle, db_session: Session, organization: Organization) -> None:
    """A second organization must never see the first organization's fuel logs,
    even when explicitly filtering by the first org's own vehicle_id."""
    client.post("/api/v1/fuel", json=_fuel_payload(vehicle.id), headers=auth_headers(admin))

    other_org = Organization(id=uuid.uuid4(), name="Tenant B", slug=f"tenant-b-{uuid.uuid4().hex[:8]}")
    db_session.add(other_org)
    db_session.commit()
    other_admin = make_user(db_session, other_org, role=UserRole.admin)

    unfiltered = client.get("/api/v1/fuel", headers=auth_headers(other_admin))
    assert unfiltered.status_code == 200
    assert unfiltered.json() == []

    # Even naming the other org's real vehicle_id explicitly must not leak it.
    filtered = client.get(f"/api/v1/fuel?vehicle_id={vehicle.id}", headers=auth_headers(other_admin))
    assert filtered.status_code == 200
    assert filtered.json() == []


def test_list_pagination_skip_and_limit(client: TestClient, admin, vehicle) -> None:
    for i in range(5):
        client.post(
            "/api/v1/fuel",
            json=_fuel_payload(vehicle.id, date=str(BASE_DATE + timedelta(days=i * 10)), odometer_reading=1000 + i * 100),
            headers=auth_headers(admin),
        )

    first_page = client.get("/api/v1/fuel?limit=2", headers=auth_headers(admin))
    assert first_page.status_code == 200
    assert len(first_page.json()) == 2

    second_page = client.get("/api/v1/fuel?skip=2&limit=2", headers=auth_headers(admin))
    assert len(second_page.json()) == 2

    first_ids = {log["id"] for log in first_page.json()}
    second_ids = {log["id"] for log in second_page.json()}
    assert first_ids.isdisjoint(second_ids)

    remainder = client.get("/api/v1/fuel?skip=4&limit=2", headers=auth_headers(admin))
    assert len(remainder.json()) == 1


def test_list_pagination_bounds_validated(client: TestClient, admin) -> None:
    assert client.get("/api/v1/fuel?skip=-1", headers=auth_headers(admin)).status_code == 422
    assert client.get("/api/v1/fuel?limit=0", headers=auth_headers(admin)).status_code == 422
    assert client.get("/api/v1/fuel?limit=501", headers=auth_headers(admin)).status_code == 422


# --- RBAC --------------------------------------------------------------------------


def test_fleet_manager_forbidden_from_writing(client: TestClient, db_session: Session, organization: Organization, vehicle) -> None:
    fm = make_user(db_session, organization, role=UserRole.fleet_manager)
    response = client.post("/api/v1/fuel", json=_fuel_payload(vehicle.id), headers=auth_headers(fm))
    assert response.status_code == 403


def test_fleet_manager_can_read_and_see_summary(client: TestClient, admin, db_session: Session, organization: Organization, vehicle) -> None:
    client.post("/api/v1/fuel", json=_fuel_payload(vehicle.id), headers=auth_headers(admin))
    fm = make_user(db_session, organization, role=UserRole.fleet_manager)
    list_resp = client.get("/api/v1/fuel", headers=auth_headers(fm))
    summary_resp = client.get(f"/api/v1/fuel/summary?month={BASE_DATE.strftime('%Y-%m')}", headers=auth_headers(fm))
    assert list_resp.status_code == 200
    assert summary_resp.status_code == 200


def test_mechanic_forbidden_on_all_fuel_routes(client: TestClient, db_session: Session, organization: Organization, vehicle) -> None:
    mechanic = make_user(db_session, organization, role=UserRole.mechanic)
    assert client.post("/api/v1/fuel", json=_fuel_payload(vehicle.id), headers=auth_headers(mechanic)).status_code == 403
    assert client.get("/api/v1/fuel", headers=auth_headers(mechanic)).status_code == 403
    assert client.get("/api/v1/fuel/summary", headers=auth_headers(mechanic)).status_code == 403


def test_driver_can_create_and_see_only_own_logs(client: TestClient, db_session: Session, organization: Organization, vehicle, driver_setup) -> None:
    driver_user, driver_profile = driver_setup
    other_driver_user = make_user(db_session, organization, role=UserRole.driver)
    make_driver(db_session, organization, user=other_driver_user)

    created = client.post("/api/v1/fuel", json=_fuel_payload(vehicle.id), headers=auth_headers(driver_user))
    assert created.status_code == 201
    assert created.json()["driver_id"] == str(driver_profile.id)

    admin_user = make_user(db_session, organization, role=UserRole.admin)
    client.post(
        "/api/v1/fuel",
        json=_fuel_payload(vehicle.id, date=str(BASE_DATE + timedelta(days=5)), odometer_reading=2000, driver_id=None),
        headers=auth_headers(admin_user),
    )

    own_list = client.get("/api/v1/fuel", headers=auth_headers(driver_user)).json()
    assert len(own_list) == 1
    assert own_list[0]["driver_id"] == str(driver_profile.id)


def test_driver_get_other_drivers_log_returns_404(client: TestClient, db_session: Session, organization: Organization, vehicle, driver_setup) -> None:
    driver_user, driver_profile = driver_setup
    other_driver_user = make_user(db_session, organization, role=UserRole.driver)
    other_driver_profile = make_driver(db_session, organization, user=other_driver_user)

    admin_user = make_user(db_session, organization, role=UserRole.admin)
    other_log = client.post(
        "/api/v1/fuel", json=_fuel_payload(vehicle.id, driver_id=str(other_driver_profile.id)), headers=auth_headers(admin_user)
    ).json()

    response = client.get(f"/api/v1/fuel/{other_log['id']}", headers=auth_headers(driver_user))
    assert response.status_code == 404
    _ = driver_profile


def test_driver_without_profile_create_rejected_and_list_empty(client: TestClient, db_session: Session, organization: Organization, vehicle) -> None:
    unlinked_driver_user = make_user(db_session, organization, role=UserRole.driver)

    create_resp = client.post("/api/v1/fuel", json=_fuel_payload(vehicle.id), headers=auth_headers(unlinked_driver_user))
    assert create_resp.status_code == 422

    list_resp = client.get("/api/v1/fuel", headers=auth_headers(unlinked_driver_user))
    assert list_resp.status_code == 200
    assert list_resp.json() == []


def test_driver_summary_forbidden(client: TestClient, driver_setup) -> None:
    driver_user, _ = driver_setup
    response = client.get("/api/v1/fuel/summary", headers=auth_headers(driver_user))
    assert response.status_code == 403
