import uuid
from datetime import date

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.models.enums import UserRole
from app.models.organization import Organization
from tests.conftest import auth_headers, make_compliance_rule, make_maintenance_log, make_part, make_user, make_vehicle

TODAY = date(2026, 9, 18)


@pytest.fixture()
def admin(db_session: Session, organization: Organization):
    return make_user(db_session, organization, role=UserRole.admin)


def _log_payload(vehicle_id, **overrides) -> dict:
    payload = {
        "vehicle_id": str(vehicle_id),
        "date": str(TODAY),
        "odometer_at_service": 5000,
        "service_type": "oil_change",
    }
    payload.update(overrides)
    return payload


def _rule_payload(**overrides) -> dict:
    payload = {
        "vehicle_make": "Toyota",
        "vehicle_model": "Hilux",
        "service_type": "oil_change",
        "interval_km": 10000,
        "interval_months": 6,
    }
    payload.update(overrides)
    return payload


# --- Maintenance router RBAC --------------------------------------------------------


@pytest.mark.parametrize("role", [UserRole.admin, UserRole.mechanic])
def test_maintenance_write_allowed_for_admin_and_mechanic(
    client: TestClient, db_session: Session, organization: Organization, role: UserRole
) -> None:
    user = make_user(db_session, organization, role=role)
    vehicle = make_vehicle(db_session, organization)
    response = client.post("/api/v1/maintenance", json=_log_payload(vehicle.id), headers=auth_headers(user))
    assert response.status_code == 201


def test_fleet_manager_forbidden_from_writing_maintenance_logs(
    client: TestClient, db_session: Session, organization: Organization
) -> None:
    """Per the literal permission-matrix reading (fleet_manager: read all, not
    full) -- confirmed intended behavior, not a bug to 'fix' by granting write."""
    fm = make_user(db_session, organization, role=UserRole.fleet_manager)
    vehicle = make_vehicle(db_session, organization)
    response = client.post("/api/v1/maintenance", json=_log_payload(vehicle.id), headers=auth_headers(fm))
    assert response.status_code == 403


def test_driver_role_forbidden_on_maintenance_routes(
    client: TestClient, db_session: Session, organization: Organization, admin
) -> None:
    vehicle = make_vehicle(db_session, organization)
    log = client.post("/api/v1/maintenance", json=_log_payload(vehicle.id), headers=auth_headers(admin)).json()
    driver = make_user(db_session, organization, role=UserRole.driver)

    assert client.get("/api/v1/maintenance", headers=auth_headers(driver)).status_code == 403
    assert client.get("/api/v1/maintenance/upcoming", headers=auth_headers(driver)).status_code == 403
    assert client.get("/api/v1/maintenance/overdue", headers=auth_headers(driver)).status_code == 403
    assert client.post("/api/v1/maintenance", json=_log_payload(vehicle.id), headers=auth_headers(driver)).status_code == 403
    assert (
        client.put(f"/api/v1/maintenance/{log['id']}", json={"cost": "10.00"}, headers=auth_headers(driver)).status_code
        == 403
    )
    assert (
        client.post(f"/api/v1/maintenance/{log['id']}/mechanic-report", json={}, headers=auth_headers(driver)).status_code
        == 403
    )


def test_mechanic_can_read_and_write_maintenance(
    client: TestClient, db_session: Session, organization: Organization, admin
) -> None:
    vehicle = make_vehicle(db_session, organization)
    mechanic = make_user(db_session, organization, role=UserRole.mechanic)

    created = client.post("/api/v1/maintenance", json=_log_payload(vehicle.id), headers=auth_headers(mechanic))
    assert created.status_code == 201

    assert client.get("/api/v1/maintenance", headers=auth_headers(mechanic)).status_code == 200
    log_id = created.json()["id"]
    assert client.put(f"/api/v1/maintenance/{log_id}", json={"cost": "50.00"}, headers=auth_headers(mechanic)).status_code == 200


def test_fleet_manager_can_read_maintenance_and_fleet_views(
    client: TestClient, db_session: Session, organization: Organization, admin
) -> None:
    vehicle = make_vehicle(db_session, organization)
    client.post("/api/v1/maintenance", json=_log_payload(vehicle.id), headers=auth_headers(admin))
    fm = make_user(db_session, organization, role=UserRole.fleet_manager)

    assert client.get("/api/v1/maintenance", headers=auth_headers(fm)).status_code == 200
    assert client.get("/api/v1/maintenance/upcoming", headers=auth_headers(fm)).status_code == 200
    assert client.get("/api/v1/maintenance/overdue", headers=auth_headers(fm)).status_code == 200


def test_mechanic_report_returns_low_stock_alerts(
    client: TestClient, db_session: Session, organization: Organization, admin
) -> None:
    vehicle = make_vehicle(db_session, organization)
    log = client.post("/api/v1/maintenance", json=_log_payload(vehicle.id), headers=auth_headers(admin)).json()
    part = make_part(db_session, organization, qty_on_hand=10, reorder_threshold=5)

    response = client.post(
        f"/api/v1/maintenance/{log['id']}/mechanic-report",
        json={"diagnostic_notes": "Belt worn", "parts_used": [{"part_id": str(part.id), "qty": 6}]},
        headers=auth_headers(admin),
    )
    assert response.status_code == 201
    body = response.json()
    assert body["low_stock_alerts"] == [{"part_id": str(part.id), "low_stock_alert": True}]

    duplicate = client.post(
        f"/api/v1/maintenance/{log['id']}/mechanic-report", json={}, headers=auth_headers(admin)
    )
    assert duplicate.status_code == 409


# --- Compliance router RBAC ----------------------------------------------------------


def test_mechanic_read_only_on_compliance_rules(
    client: TestClient, db_session: Session, organization: Organization, admin
) -> None:
    client.post("/api/v1/compliance/rules", json=_rule_payload(), headers=auth_headers(admin))
    mechanic = make_user(db_session, organization, role=UserRole.mechanic)

    assert client.get("/api/v1/compliance/rules", headers=auth_headers(mechanic)).status_code == 200
    assert client.post("/api/v1/compliance/rules", json=_rule_payload(vehicle_model="Corolla"), headers=auth_headers(mechanic)).status_code == 403


def test_driver_role_forbidden_on_compliance_routes(
    client: TestClient, db_session: Session, organization: Organization, admin
) -> None:
    vehicle = make_vehicle(db_session, organization, make="Toyota", model="Hilux")
    driver = make_user(db_session, organization, role=UserRole.driver)

    assert client.get("/api/v1/compliance/rules", headers=auth_headers(driver)).status_code == 403
    assert client.get("/api/v1/compliance/status", headers=auth_headers(driver)).status_code == 403
    assert client.get(f"/api/v1/compliance/status/{vehicle.id}", headers=auth_headers(driver)).status_code == 403
    assert client.post("/api/v1/compliance/rules", json=_rule_payload(), headers=auth_headers(driver)).status_code == 403


def test_mechanic_can_read_compliance_status(
    client: TestClient, db_session: Session, organization: Organization, admin
) -> None:
    vehicle = make_vehicle(db_session, organization, make="Toyota", model="Hilux")
    make_compliance_rule(db_session, organization)
    mechanic = make_user(db_session, organization, role=UserRole.mechanic)

    assert client.get(f"/api/v1/compliance/status/{vehicle.id}", headers=auth_headers(mechanic)).status_code == 200
    assert client.get("/api/v1/compliance/status", headers=auth_headers(mechanic)).status_code == 200


def test_vehicle_compliance_route_matches_compliance_status_route(
    client: TestClient, db_session: Session, organization: Organization, admin
) -> None:
    vehicle = make_vehicle(db_session, organization, make="Toyota", model="Hilux", current_odometer=1000)
    make_compliance_rule(db_session, organization, interval_km=10000, interval_months=12)
    make_maintenance_log(db_session, organization, vehicle, odometer_at_service=900)

    via_vehicles = client.get(f"/api/v1/vehicles/{vehicle.id}/compliance", headers=auth_headers(admin)).json()
    via_compliance = client.get(f"/api/v1/compliance/status/{vehicle.id}", headers=auth_headers(admin)).json()
    assert via_vehicles == via_compliance


@pytest.mark.parametrize("role", [UserRole.driver, UserRole.mechanic, UserRole.fleet_manager])
def test_vehicle_compliance_route_open_to_all_roles(
    client: TestClient, db_session: Session, organization: Organization, role: UserRole
) -> None:
    vehicle = make_vehicle(db_session, organization, make="Toyota", model="Hilux")
    user = make_user(db_session, organization, role=role)
    response = client.get(f"/api/v1/vehicles/{vehicle.id}/compliance", headers=auth_headers(user))
    assert response.status_code == 200


def test_admin_succeeds_on_every_route_in_both_routers(
    client: TestClient, db_session: Session, organization: Organization, admin
) -> None:
    vehicle = make_vehicle(db_session, organization, make="Toyota", model="Hilux")
    log = client.post("/api/v1/maintenance", json=_log_payload(vehicle.id), headers=auth_headers(admin)).json()
    rule = client.post("/api/v1/compliance/rules", json=_rule_payload(), headers=auth_headers(admin)).json()

    assert client.get("/api/v1/maintenance", headers=auth_headers(admin)).status_code == 200
    assert client.get(f"/api/v1/maintenance/{log['id']}", headers=auth_headers(admin)).status_code == 200
    assert client.put(f"/api/v1/maintenance/{log['id']}", json={"cost": "1.00"}, headers=auth_headers(admin)).status_code == 200
    assert client.get("/api/v1/maintenance/upcoming", headers=auth_headers(admin)).status_code == 200
    assert client.get("/api/v1/maintenance/overdue", headers=auth_headers(admin)).status_code == 200
    assert client.get("/api/v1/compliance/rules", headers=auth_headers(admin)).status_code == 200
    assert client.put(f"/api/v1/compliance/rules/{rule['id']}", json={"interval_km": 12000}, headers=auth_headers(admin)).status_code == 200
    assert client.get("/api/v1/compliance/status", headers=auth_headers(admin)).status_code == 200
    assert client.get(f"/api/v1/compliance/status/{vehicle.id}", headers=auth_headers(admin)).status_code == 200


# --- Multi-tenant isolation --------------------------------------------------------------


@pytest.fixture()
def other_org_admin(db_session: Session):
    other_org = Organization(id=uuid.uuid4(), name="Other Co", slug=f"other-{uuid.uuid4().hex[:8]}")
    db_session.add(other_org)
    db_session.commit()
    return make_user(db_session, other_org, role=UserRole.admin)


def test_cross_tenant_maintenance_log_returns_404(
    client: TestClient, db_session: Session, organization: Organization, admin, other_org_admin
) -> None:
    vehicle = make_vehicle(db_session, organization)
    log = client.post("/api/v1/maintenance", json=_log_payload(vehicle.id), headers=auth_headers(admin)).json()

    assert client.get(f"/api/v1/maintenance/{log['id']}", headers=auth_headers(other_org_admin)).status_code == 404
    assert (
        client.put(f"/api/v1/maintenance/{log['id']}", json={"cost": "1.00"}, headers=auth_headers(other_org_admin)).status_code
        == 404
    )


def test_cross_tenant_compliance_rule_returns_404(
    client: TestClient, db_session: Session, organization: Organization, admin, other_org_admin
) -> None:
    rule = client.post("/api/v1/compliance/rules", json=_rule_payload(), headers=auth_headers(admin)).json()
    response = client.put(
        f"/api/v1/compliance/rules/{rule['id']}", json={"interval_km": 1}, headers=auth_headers(other_org_admin)
    )
    assert response.status_code == 404


def test_cross_tenant_vehicle_compliance_returns_404(
    client: TestClient, db_session: Session, organization: Organization, other_org_admin
) -> None:
    vehicle = make_vehicle(db_session, organization, make="Toyota", model="Hilux")
    response = client.get(f"/api/v1/compliance/status/{vehicle.id}", headers=auth_headers(other_org_admin))
    assert response.status_code == 404
