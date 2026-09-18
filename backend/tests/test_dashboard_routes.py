import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.models.enums import UserRole
from app.models.organization import Organization
from tests.conftest import auth_headers, make_user

DASHBOARD_ROUTES = [
    "/api/v1/dashboard/summary",
    "/api/v1/dashboard/fuel-trends",
    "/api/v1/dashboard/maintenance-calendar",
    "/api/v1/dashboard/fleet-health",
]


@pytest.mark.parametrize("role", [UserRole.driver, UserRole.mechanic])
def test_driver_and_mechanic_forbidden_on_all_dashboard_routes(
    client: TestClient, db_session: Session, organization: Organization, role: UserRole
) -> None:
    user = make_user(db_session, organization, role=role)
    for route in DASHBOARD_ROUTES:
        response = client.get(route, headers=auth_headers(user))
        assert response.status_code == 403, f"{route} did not 403 for {role}"


@pytest.mark.parametrize("role", [UserRole.admin, UserRole.fleet_manager])
def test_admin_and_fleet_manager_succeed_on_all_dashboard_routes(
    client: TestClient, db_session: Session, organization: Organization, role: UserRole
) -> None:
    user = make_user(db_session, organization, role=role)
    for route in DASHBOARD_ROUTES:
        response = client.get(route, headers=auth_headers(user))
        assert response.status_code == 200, f"{route} did not 200 for {role}"


def test_fuel_trends_months_bounds_validated(client: TestClient, db_session: Session, organization: Organization) -> None:
    admin = make_user(db_session, organization, role=UserRole.admin)
    assert client.get("/api/v1/dashboard/fuel-trends?months=0", headers=auth_headers(admin)).status_code == 422
    assert client.get("/api/v1/dashboard/fuel-trends?months=25", headers=auth_headers(admin)).status_code == 422
    assert client.get("/api/v1/dashboard/fuel-trends?months=-1", headers=auth_headers(admin)).status_code == 422
    assert client.get("/api/v1/dashboard/fuel-trends?months=12", headers=auth_headers(admin)).status_code == 200


def test_maintenance_calendar_window_days_bounds_validated(client: TestClient, db_session: Session, organization: Organization) -> None:
    admin = make_user(db_session, organization, role=UserRole.admin)
    assert client.get("/api/v1/dashboard/maintenance-calendar?window_days=0", headers=auth_headers(admin)).status_code == 422
    assert client.get("/api/v1/dashboard/maintenance-calendar?window_days=366", headers=auth_headers(admin)).status_code == 422
    assert client.get("/api/v1/dashboard/maintenance-calendar?window_days=30", headers=auth_headers(admin)).status_code == 200


def test_summary_response_shape(client: TestClient, db_session: Session, organization: Organization) -> None:
    admin = make_user(db_session, organization, role=UserRole.admin)
    response = client.get("/api/v1/dashboard/summary", headers=auth_headers(admin))
    assert response.status_code == 200
    body = response.json()
    for field in ("total_vehicles", "active_drivers", "month_fuel_cost", "overdue_maintenance_count", "low_stock_parts_count", "open_incidents_count"):
        assert field in body
