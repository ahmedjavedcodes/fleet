import uuid
from datetime import date, datetime, timezone

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.models.enums import UserRole
from app.models.organization import Organization
from tests.conftest import auth_headers, make_driver, make_user, make_vehicle

START = "2026-06-01T09:00:00Z"
END = "2026-06-01T14:00:00Z"


@pytest.fixture()
def admin(db_session: Session, organization: Organization):
    return make_user(db_session, organization, role=UserRole.admin)


@pytest.fixture()
def driver_setup(db_session: Session, organization: Organization):
    driver_user = make_user(db_session, organization, role=UserRole.driver)
    driver_profile = make_driver(db_session, organization, user=driver_user)
    return driver_user, driver_profile


def _trip_payload(driver_id, vehicle_id, **overrides) -> dict:
    payload = {
        "driver_id": str(driver_id), "vehicle_id": str(vehicle_id),
        "start_time": START, "end_time": END, "start_odometer": 1000, "end_odometer": 1100,
    }
    payload.update(overrides)
    return payload


def _report_payload(driver_id, vehicle_id, **overrides) -> dict:
    payload = {
        "driver_id": str(driver_id), "vehicle_id": str(vehicle_id),
        "shift_date": "2026-06-01", "vehicle_condition": "good",
    }
    payload.update(overrides)
    return payload


def _incident_payload(vehicle_id, **overrides) -> dict:
    payload = {
        "vehicle_id": str(vehicle_id), "incident_type": "damage", "date": "2026-06-01",
        "severity": "moderate", "description": "Dented fender",
    }
    payload.update(overrides)
    return payload


# --- Trips router RBAC -----------------------------------------------------------


def test_driver_can_create_and_list_own_trips(client: TestClient, db_session: Session, organization: Organization, driver_setup) -> None:
    driver_user, driver_profile = driver_setup
    vehicle = make_vehicle(db_session, organization)

    created = client.post("/api/v1/trips", json=_trip_payload(driver_profile.id, vehicle.id), headers=auth_headers(driver_user))
    assert created.status_code == 201

    listed = client.get("/api/v1/trips", headers=auth_headers(driver_user))
    assert len(listed.json()) == 1


def test_driver_own_only_filter_on_trips_and_reports(
    client: TestClient, db_session: Session, organization: Organization, admin
) -> None:
    vehicle = make_vehicle(db_session, organization)
    driver_a_user = make_user(db_session, organization, role=UserRole.driver)
    driver_a = make_driver(db_session, organization, user=driver_a_user)
    driver_b_user = make_user(db_session, organization, role=UserRole.driver)
    driver_b = make_driver(db_session, organization, user=driver_b_user)

    client.post("/api/v1/trips", json=_trip_payload(driver_a.id, vehicle.id), headers=auth_headers(admin))
    client.post("/api/v1/trips", json=_trip_payload(driver_b.id, vehicle.id), headers=auth_headers(admin))
    client.post("/api/v1/driver-reports", json=_report_payload(driver_a.id, vehicle.id), headers=auth_headers(admin))
    client.post("/api/v1/driver-reports", json=_report_payload(driver_b.id, vehicle.id), headers=auth_headers(admin))

    trips_a = client.get("/api/v1/trips", headers=auth_headers(driver_a_user)).json()
    reports_a = client.get("/api/v1/driver-reports", headers=auth_headers(driver_a_user)).json()
    assert len(trips_a) == 1 and trips_a[0]["driver_id"] == str(driver_a.id)
    assert len(reports_a) == 1 and reports_a[0]["driver_id"] == str(driver_a.id)


def test_fleet_manager_can_read_but_not_write_trips(client: TestClient, db_session: Session, organization: Organization) -> None:
    vehicle = make_vehicle(db_session, organization)
    fm = make_user(db_session, organization, role=UserRole.fleet_manager)
    driver_profile = make_driver(db_session, organization)

    assert client.get("/api/v1/trips", headers=auth_headers(fm)).status_code == 200
    assert client.post("/api/v1/trips", json=_trip_payload(driver_profile.id, vehicle.id), headers=auth_headers(fm)).status_code == 403


def test_mechanic_forbidden_on_all_routes(client: TestClient, db_session: Session, organization: Organization) -> None:
    vehicle = make_vehicle(db_session, organization)
    driver_profile = make_driver(db_session, organization)
    mechanic = make_user(db_session, organization, role=UserRole.mechanic)

    assert client.get("/api/v1/trips", headers=auth_headers(mechanic)).status_code == 403
    assert client.post("/api/v1/trips", json=_trip_payload(driver_profile.id, vehicle.id), headers=auth_headers(mechanic)).status_code == 403
    assert client.get("/api/v1/driver-reports", headers=auth_headers(mechanic)).status_code == 403
    assert client.post("/api/v1/driver-reports", json=_report_payload(driver_profile.id, vehicle.id), headers=auth_headers(mechanic)).status_code == 403
    assert client.get("/api/v1/incidents", headers=auth_headers(mechanic)).status_code == 403
    assert client.post("/api/v1/incidents", json=_incident_payload(vehicle.id), headers=auth_headers(mechanic)).status_code == 403


# --- Driver reports: append-only ---------------------------------------------------


def test_driver_report_has_no_update_route(client: TestClient, db_session: Session, organization: Organization, admin) -> None:
    vehicle = make_vehicle(db_session, organization)
    driver_profile = make_driver(db_session, organization)
    report = client.post("/api/v1/driver-reports", json=_report_payload(driver_profile.id, vehicle.id), headers=auth_headers(admin)).json()

    put_resp = client.put(f"/api/v1/driver-reports/{report['id']}", json={"handover_notes": "edited"}, headers=auth_headers(admin))
    patch_resp = client.patch(f"/api/v1/driver-reports/{report['id']}", json={"handover_notes": "edited"}, headers=auth_headers(admin))
    assert put_resp.status_code == 405
    assert patch_resp.status_code == 405


# --- Incidents: partial immutability + inferred RBAC ------------------------------


def test_incident_resolution_update_ignores_immutable_fields(
    client: TestClient, db_session: Session, organization: Organization, admin
) -> None:
    vehicle = make_vehicle(db_session, organization)
    incident = client.post("/api/v1/incidents", json=_incident_payload(vehicle.id), headers=auth_headers(admin)).json()

    response = client.put(
        f"/api/v1/incidents/{incident['id']}",
        json={"resolution_status": "resolved", "resolution_notes": "done", "description": "hijacked", "severity": "critical"},
        headers=auth_headers(admin),
    )
    assert response.status_code == 422  # extra='forbid' rejects unknown fields


def test_driver_can_file_but_not_resolve_incidents(client: TestClient, db_session: Session, organization: Organization, driver_setup) -> None:
    driver_user, driver_profile = driver_setup
    vehicle = make_vehicle(db_session, organization)

    created = client.post("/api/v1/incidents", json=_incident_payload(vehicle.id, driver_id=str(driver_profile.id)), headers=auth_headers(driver_user))
    assert created.status_code == 201

    resolve_resp = client.put(
        f"/api/v1/incidents/{created.json()['id']}",
        json={"resolution_status": "resolved"},
        headers=auth_headers(driver_user),
    )
    assert resolve_resp.status_code == 403


def test_fleet_manager_can_resolve_incidents(client: TestClient, db_session: Session, organization: Organization, admin) -> None:
    vehicle = make_vehicle(db_session, organization)
    incident = client.post("/api/v1/incidents", json=_incident_payload(vehicle.id), headers=auth_headers(admin)).json()
    fm = make_user(db_session, organization, role=UserRole.fleet_manager)

    response = client.put(f"/api/v1/incidents/{incident['id']}", json={"resolution_status": "investigating"}, headers=auth_headers(fm))
    assert response.status_code == 200
    assert response.json()["resolution_status"] == "investigating"


# --- Timeline routes --------------------------------------------------------------


@pytest.mark.parametrize("role", [UserRole.admin, UserRole.fleet_manager, UserRole.driver, UserRole.mechanic])
def test_vehicle_timeline_open_to_all_roles(client: TestClient, db_session: Session, organization: Organization, role: UserRole) -> None:
    vehicle = make_vehicle(db_session, organization)
    user = make_user(db_session, organization, role=role)
    response = client.get(f"/api/v1/vehicles/{vehicle.id}/timeline", headers=auth_headers(user))
    assert response.status_code == 200


def test_driver_can_view_own_timeline_not_anothers(client: TestClient, db_session: Session, organization: Organization, driver_setup) -> None:
    driver_user, driver_profile = driver_setup
    other_driver = make_driver(db_session, organization)

    own = client.get(f"/api/v1/drivers/{driver_profile.id}/timeline", headers=auth_headers(driver_user))
    other = client.get(f"/api/v1/drivers/{other_driver.id}/timeline", headers=auth_headers(driver_user))
    assert own.status_code == 200
    assert other.status_code == 403


def test_mechanic_forbidden_on_driver_timeline(client: TestClient, db_session: Session, organization: Organization) -> None:
    driver_profile = make_driver(db_session, organization)
    mechanic = make_user(db_session, organization, role=UserRole.mechanic)
    response = client.get(f"/api/v1/drivers/{driver_profile.id}/timeline", headers=auth_headers(mechanic))
    assert response.status_code == 403


# --- Multi-tenant isolation --------------------------------------------------------------


@pytest.fixture()
def other_org_admin(db_session: Session):
    other_org = Organization(id=uuid.uuid4(), name="Other Co", slug=f"other-{uuid.uuid4().hex[:8]}")
    db_session.add(other_org)
    db_session.commit()
    return make_user(db_session, other_org, role=UserRole.admin)


def test_cross_tenant_trip_returns_404(client: TestClient, db_session: Session, organization: Organization, admin, other_org_admin) -> None:
    vehicle = make_vehicle(db_session, organization)
    driver_profile = make_driver(db_session, organization)
    trip = client.post("/api/v1/trips", json=_trip_payload(driver_profile.id, vehicle.id), headers=auth_headers(admin)).json()

    response = client.get(f"/api/v1/trips/{trip['id']}", headers=auth_headers(other_org_admin))
    assert response.status_code == 404


def test_cross_tenant_incident_returns_404(client: TestClient, db_session: Session, organization: Organization, admin, other_org_admin) -> None:
    vehicle = make_vehicle(db_session, organization)
    incident = client.post("/api/v1/incidents", json=_incident_payload(vehicle.id), headers=auth_headers(admin)).json()

    response = client.get(f"/api/v1/incidents/{incident['id']}", headers=auth_headers(other_org_admin))
    assert response.status_code == 404


def test_cross_tenant_driver_report_returns_404(client: TestClient, db_session: Session, organization: Organization, admin, other_org_admin) -> None:
    vehicle = make_vehicle(db_session, organization)
    driver_profile = make_driver(db_session, organization)
    report = client.post("/api/v1/driver-reports", json=_report_payload(driver_profile.id, vehicle.id), headers=auth_headers(admin)).json()

    response = client.get(f"/api/v1/driver-reports/{report['id']}", headers=auth_headers(other_org_admin))
    assert response.status_code == 404
