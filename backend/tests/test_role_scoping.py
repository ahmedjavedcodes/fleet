"""Row-level data scoping: a Driver sees only their own records and a Mechanic only
the maintenance jobs they recorded, while admin / fleet_manager see everything.

Each test builds two people's data and asserts the caller gets exactly their own
slice from the list AND the detail endpoint (a foreign record is a 404, never a
403, so its existence isn't disclosed)."""

from datetime import datetime, timezone

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.models.enums import UserRole
from app.models.organization import Organization
from tests.conftest import auth_headers, make_assignment, make_driver, make_maintenance_log, make_user, make_vehicle


def _two_drivers(db_session: Session, organization: Organization):
    """(admin, vehicle, (user_a, driver_a), (user_b, driver_b))."""
    admin = make_user(db_session, organization, role=UserRole.admin)
    vehicle = make_vehicle(db_session, organization)
    user_a = make_user(db_session, organization, role=UserRole.driver)
    user_b = make_user(db_session, organization, role=UserRole.driver)
    driver_a = make_driver(db_session, organization, user=user_a, full_name="Driver A")
    driver_b = make_driver(db_session, organization, user=user_b, full_name="Driver B")
    return admin, vehicle, (user_a, driver_a), (user_b, driver_b)


def _trip(client: TestClient, admin, vehicle, driver, start_odo: int) -> dict:
    response = client.post(
        "/api/v1/trips",
        json={
            "driver_id": str(driver.id),
            "vehicle_id": str(vehicle.id),
            "start_time": "2026-09-01T08:00:00Z",
            "end_time": "2026-09-01T10:00:00Z",
            "start_odometer": start_odo,
            "end_odometer": start_odo + 50,
        },
        headers=auth_headers(admin),
    )
    assert response.status_code == 201, response.text
    return response.json()


def _fuel(client: TestClient, admin, vehicle, driver, odometer: int) -> dict:
    response = client.post(
        "/api/v1/fuel",
        json={
            "vehicle_id": str(vehicle.id),
            "driver_id": str(driver.id),
            "date": "2026-09-01",
            "odometer_reading": odometer,
            "liters_filled": "40.00",
            "price_per_liter": "2.50",
            "total_cost": "100.00",
        },
        headers=auth_headers(admin),
    )
    assert response.status_code == 201, response.text
    return response.json()


def _incident(client: TestClient, admin, vehicle, driver) -> dict:
    response = client.post(
        "/api/v1/incidents",
        json={
            "vehicle_id": str(vehicle.id),
            "driver_id": str(driver.id),
            "incident_type": "damage",
            "date": "2026-09-01",
            "severity": "minor",
            "description": "Scratch",
        },
        headers=auth_headers(admin),
    )
    assert response.status_code == 201, response.text
    return response.json()


# --- Driver: trips / fuel / incidents ---------------------------------------------


def test_driver_lists_and_reads_only_own_trips(client: TestClient, db_session: Session, organization: Organization) -> None:
    admin, vehicle, (user_a, driver_a), (_, driver_b) = _two_drivers(db_session, organization)
    mine = _trip(client, admin, vehicle, driver_a, 100)
    theirs = _trip(client, admin, vehicle, driver_b, 300)

    listed = client.get("/api/v1/trips", headers=auth_headers(user_a))
    assert listed.status_code == 200
    assert [t["id"] for t in listed.json()] == [mine["id"]]
    assert client.get(f"/api/v1/trips/{mine['id']}", headers=auth_headers(user_a)).status_code == 200
    assert client.get(f"/api/v1/trips/{theirs['id']}", headers=auth_headers(user_a)).status_code == 404
    # Asking for someone else's driver_id explicitly must not widen the result.
    widened = client.get("/api/v1/trips", params={"driver_id": str(driver_b.id)}, headers=auth_headers(user_a))
    assert widened.json() == []

    assert len(client.get("/api/v1/trips", headers=auth_headers(admin)).json()) == 2


def test_driver_lists_and_reads_only_own_fuel_logs(client: TestClient, db_session: Session, organization: Organization) -> None:
    admin, vehicle, (user_a, driver_a), (_, driver_b) = _two_drivers(db_session, organization)
    mine = _fuel(client, admin, vehicle, driver_a, 1000)
    theirs = _fuel(client, admin, vehicle, driver_b, 1400)

    listed = client.get("/api/v1/fuel", headers=auth_headers(user_a))
    assert [f["id"] for f in listed.json()] == [mine["id"]]
    assert client.get(f"/api/v1/fuel/{theirs['id']}", headers=auth_headers(user_a)).status_code == 404
    assert len(client.get("/api/v1/fuel", headers=auth_headers(admin)).json()) == 2


def test_driver_lists_and_reads_only_own_incidents(client: TestClient, db_session: Session, organization: Organization) -> None:
    admin, vehicle, (user_a, driver_a), (_, driver_b) = _two_drivers(db_session, organization)
    mine = _incident(client, admin, vehicle, driver_a)
    theirs = _incident(client, admin, vehicle, driver_b)

    listed = client.get("/api/v1/incidents", headers=auth_headers(user_a))
    assert [i["id"] for i in listed.json()] == [mine["id"]]
    assert client.get(f"/api/v1/incidents/{theirs['id']}", headers=auth_headers(user_a)).status_code == 404
    assert len(client.get("/api/v1/incidents", headers=auth_headers(admin)).json()) == 2


def test_unlinked_driver_user_sees_nothing(client: TestClient, db_session: Session, organization: Organization) -> None:
    admin, vehicle, (_, driver_a), _ = _two_drivers(db_session, organization)
    _trip(client, admin, vehicle, driver_a, 100)
    orphan = make_user(db_session, organization, role=UserRole.driver)  # no Driver profile

    assert client.get("/api/v1/trips", headers=auth_headers(orphan)).json() == []
    assert client.get("/api/v1/fuel", headers=auth_headers(orphan)).json() == []
    assert client.get("/api/v1/incidents", headers=auth_headers(orphan)).json() == []


# --- Driver: assignments ----------------------------------------------------------


def test_driver_vehicle_assignment_history_hides_other_drivers(
    client: TestClient, db_session: Session, organization: Organization
) -> None:
    admin, vehicle, (user_a, driver_a), (_, driver_b) = _two_drivers(db_session, organization)
    mine = make_assignment(
        db_session, organization, vehicle, driver_a,
        assigned_at=datetime(2026, 1, 1, tzinfo=timezone.utc), released_at=datetime(2026, 3, 1, tzinfo=timezone.utc),
    )
    make_assignment(db_session, organization, vehicle, driver_b, assigned_at=datetime(2026, 3, 2, tzinfo=timezone.utc))

    as_driver = client.get(f"/api/v1/vehicles/{vehicle.id}/assignments", headers=auth_headers(user_a))
    assert as_driver.status_code == 200
    assert [a["id"] for a in as_driver.json()] == [str(mine.id)]
    assert {a["driver_name"] for a in as_driver.json()} == {"Driver A"}

    as_admin = client.get(f"/api/v1/vehicles/{vehicle.id}/assignments", headers=auth_headers(admin))
    assert len(as_admin.json()) == 2


def test_driver_cannot_read_another_drivers_assignment_history(
    client: TestClient, db_session: Session, organization: Organization
) -> None:
    _, _, (user_a, driver_a), (_, driver_b) = _two_drivers(db_session, organization)
    assert client.get(f"/api/v1/drivers/{driver_a.id}/assignments", headers=auth_headers(user_a)).status_code == 200
    assert client.get(f"/api/v1/drivers/{driver_b.id}/assignments", headers=auth_headers(user_a)).status_code == 403


# --- Mechanic: maintenance --------------------------------------------------------


def test_mechanic_lists_and_reads_only_jobs_they_recorded(
    client: TestClient, db_session: Session, organization: Organization
) -> None:
    admin = make_user(db_session, organization, role=UserRole.admin)
    manager = make_user(db_session, organization, role=UserRole.fleet_manager)
    mech_a = make_user(db_session, organization, role=UserRole.mechanic)
    mech_b = make_user(db_session, organization, role=UserRole.mechanic)
    vehicle = make_vehicle(db_session, organization)
    mine = make_maintenance_log(db_session, organization, vehicle, created_by=mech_a.id)
    theirs = make_maintenance_log(db_session, organization, vehicle, created_by=mech_b.id)
    by_admin = make_maintenance_log(db_session, organization, vehicle, created_by=admin.id)

    listed = client.get("/api/v1/maintenance", headers=auth_headers(mech_a))
    assert listed.status_code == 200
    assert [m["id"] for m in listed.json()] == [str(mine.id)]
    assert client.get(f"/api/v1/maintenance/{mine.id}", headers=auth_headers(mech_a)).status_code == 200
    assert client.get(f"/api/v1/maintenance/{theirs.id}", headers=auth_headers(mech_a)).status_code == 404
    assert client.get(f"/api/v1/maintenance/{by_admin.id}", headers=auth_headers(mech_a)).status_code == 404

    for viewer in (admin, manager):
        assert len(client.get("/api/v1/maintenance", headers=auth_headers(viewer)).json()) == 3
        assert client.get(f"/api/v1/maintenance/{theirs.id}", headers=auth_headers(viewer)).status_code == 200


def test_mechanic_created_log_is_visible_to_that_mechanic(
    client: TestClient, db_session: Session, organization: Organization
) -> None:
    """End to end: a job recorded through the API is attributed to the caller, so it
    shows up in their own scoped list (not just rows seeded with created_by)."""
    mech = make_user(db_session, organization, role=UserRole.mechanic)
    other = make_user(db_session, organization, role=UserRole.mechanic)
    vehicle = make_vehicle(db_session, organization)
    created = client.post(
        "/api/v1/maintenance",
        json={
            "vehicle_id": str(vehicle.id),
            "date": "2026-09-01",
            "odometer_at_service": 5000,
            "service_types": ["oil_change"],
        },
        headers=auth_headers(mech),
    )
    assert created.status_code == 201, created.text

    assert [m["id"] for m in client.get("/api/v1/maintenance", headers=auth_headers(mech)).json()] == [created.json()["id"]]
    assert client.get("/api/v1/maintenance", headers=auth_headers(other)).json() == []


# --- What the driver / mechanic pages call must load (200), not 403 -----------------


def test_driver_list_views_load_without_forbidden(client: TestClient, db_session: Session, organization: Organization) -> None:
    _, vehicle, (user_a, driver_a), _ = _two_drivers(db_session, organization)
    headers = auth_headers(user_a)
    for path in (
        "/api/v1/trips",
        "/api/v1/fuel",
        "/api/v1/incidents",
        "/api/v1/driver-reports",
        "/api/v1/vehicles",
        f"/api/v1/vehicles/{vehicle.id}/assignments",
        f"/api/v1/drivers/{driver_a.id}/assignments",
    ):
        assert client.get(path, headers=headers).status_code == 200, path
    # Maintenance is a fleet/mechanic area -- a driver has no view of it at all.
    assert client.get("/api/v1/maintenance", headers=headers).status_code == 403


def test_mechanic_list_views_load_without_forbidden(client: TestClient, db_session: Session, organization: Organization) -> None:
    mech = make_user(db_session, organization, role=UserRole.mechanic)
    headers = auth_headers(mech)
    for path in ("/api/v1/maintenance", "/api/v1/vehicles", "/api/v1/drivers"):
        assert client.get(path, headers=headers).status_code == 200, path
    # Driver-side records are not a mechanic's to read.
    for path in ("/api/v1/trips", "/api/v1/fuel", "/api/v1/incidents"):
        assert client.get(path, headers=headers).status_code == 403, path
