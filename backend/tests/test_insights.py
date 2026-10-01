"""Search and filters on the fleet-health (insights) and dashboard lists: applied before paging, with a filtered X-Total-Count."""

from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.models.enums import IncidentSeverity, UserRole, VehicleStatus
from app.models.organization import Organization
from tests.conftest import auth_headers, make_driver, make_maintenance_log, make_user, make_vehicle
from tests.test_dashboard_performance import make_incident

URL = "/api/v1/dashboard/fleet-health"
NOW = datetime.now(timezone.utc).date()


@pytest.fixture()
def fleet(db_session: Session, organization: Organization):
    admin = make_user(db_session, organization, role=UserRole.admin)
    # Health = the mean of the incident signal and a clean maintenance signal: 0 incidents 100, 1 -> 85, 2 -> 70, 3 -> 55.
    spec = [("TST-001", "Toyota", "Hilux", 0), ("TST-002", "Ford", "Ranger", 1), ("TST-003", "Toyota", "Corolla", 2), ("TST-004", "Isuzu", "D-Max", 3)]
    vehicles = {}
    for plate, make, model, incidents in spec:
        vehicle = make_vehicle(db_session, organization, plate_number=plate, make=make, model=model)
        vehicles[plate] = vehicle
        for _ in range(incidents):
            make_incident(db_session, organization, vehicle, admin, severity=IncidentSeverity.minor)
    vehicles["TST-005"] = make_vehicle(db_session, organization, plate_number="TST-005", make="Toyota", model="Hiace", status=VehicleStatus.maintenance)
    vehicles["TST-006"] = make_vehicle(db_session, organization, plate_number="TST-006", make="Ford", model="Transit", status=VehicleStatus.retired)
    return admin, vehicles


def get(client, admin, **params):
    response = client.get(URL, params=params, headers=auth_headers(admin))
    assert response.status_code == 200, response.text
    return [r["plate_number"] for r in response.json()], int(response.headers["x-total-count"])


def test_no_filters_keeps_the_default_behaviour(client: TestClient, db_session: Session, organization: Organization, fleet) -> None:
    admin, _ = fleet
    plates, total = get(client, admin)
    assert total == 5 and len(plates) == 5 and "TST-006" not in plates  # retired are left out by default

    paged, paged_total = get(client, admin, limit=25)
    assert paged_total == 5 and paged[0] == "TST-004"  # worst first


def test_health_min_and_max_filter_the_scores_and_the_total(client: TestClient, db_session: Session, organization: Organization, fleet) -> None:
    admin, _ = fleet
    assert get(client, admin, health_max=60, limit=25) == (["TST-004"], 1)
    assert get(client, admin, health_min=80, limit=25)[1] == 3  # 100 (TST-001, TST-005) and 85 (TST-002)
    plates, total = get(client, admin, health_min=60, health_max=90, limit=25)
    assert sorted(plates) == ["TST-002", "TST-003"] and total == 2
    assert get(client, admin, health_min=100, limit=25)[1] == 2


def test_the_total_is_the_filtered_count_across_pages(client: TestClient, db_session: Session, organization: Organization, fleet) -> None:
    admin, _ = fleet
    first, total = get(client, admin, health_min=60, limit=2)
    second, total_second = get(client, admin, health_min=60, limit=2, offset=2)
    assert total == total_second == 4 and len(first) == 2 and len(second) == 2 and not set(first) & set(second)


def test_search_matches_plate_make_model_and_make_model_case_insensitively(client: TestClient, db_session: Session, organization: Organization, fleet) -> None:
    admin, _ = fleet
    assert get(client, admin, search="tst-003")[0] == ["TST-003"]
    assert sorted(get(client, admin, search="toyota")[0]) == ["TST-001", "TST-003", "TST-005"]
    assert get(client, admin, search="ford ranger")[0] == ["TST-002"]
    assert get(client, admin, search="d-max")[0] == ["TST-004"]
    assert get(client, admin, search="no such vehicle") == ([], 0)
    assert get(client, admin, search="%")[1] == 0  # a wildcard is a literal, not "match everything"


def test_make_and_status_filters_combine_with_search_and_health(client: TestClient, db_session: Session, organization: Organization, fleet) -> None:
    admin, _ = fleet
    assert sorted(get(client, admin, make="Toyota")[0]) == ["TST-001", "TST-003", "TST-005"]
    assert get(client, admin, status="maintenance")[0] == ["TST-005"]
    assert get(client, admin, status="retired")[0] == ["TST-006"]  # asking for retired includes them
    assert get(client, admin, make="Toyota", health_max=90, search="cor")[0] == ["TST-003"]


def test_bad_filter_values_are_rejected(client: TestClient, db_session: Session, organization: Organization, fleet) -> None:
    admin, _ = fleet
    for bad in ({"health_min": -1}, {"health_max": 101}, {"status": "flying"}):
        assert client.get(URL, params=bad, headers=auth_headers(admin)).status_code == 422


def test_the_makes_dropdown_lists_distinct_makes(client: TestClient, db_session: Session, organization: Organization, fleet) -> None:
    admin, _ = fleet
    assert client.get("/api/v1/dashboard/fleet-makes", headers=auth_headers(admin)).json() == ["Ford", "Isuzu", "Toyota"]


def test_calendar_search_matches_vehicle_or_driver(client: TestClient, db_session: Session, organization: Organization, fleet) -> None:
    admin, vehicles = fleet
    driver = make_driver(db_session, organization, full_name="Zainab Qureshi")
    for plate in ("TST-001", "TST-002"):
        make_maintenance_log(db_session, organization, vehicles[plate], odometer_at_service=1, next_due_km=None, next_due_date=NOW - timedelta(days=5),
                             **({"driver_id": driver.id} if plate == "TST-002" else {}))
    run = lambda **p: client.get("/api/v1/dashboard/maintenance-calendar", params=p, headers=auth_headers(admin))  # noqa: E731

    assert run().headers["x-total-count"] == "2"
    by_plate = run(search="TST-001")
    assert [i["plate_number"] for i in by_plate.json()] == ["TST-001"] and by_plate.headers["x-total-count"] == "1"
    by_driver = run(search="zainab", limit=25)
    assert [i["plate_number"] for i in by_driver.json()] == ["TST-002"] and by_driver.headers["x-total-count"] == "1"


def test_incident_search_matches_description_vehicle_or_driver(client: TestClient, db_session: Session, organization: Organization, fleet) -> None:
    admin, vehicles = fleet
    make_incident(db_session, organization, vehicles["TST-001"], admin, description="Windscreen cracked by a stone")
    make_incident(db_session, organization, vehicles["TST-002"], admin, description="Door dent")
    run = lambda term: [i["description"] for i in client.get("/api/v1/incidents", params={"search": term}, headers=auth_headers(admin)).json()]  # noqa: E731

    assert run("windscreen") == ["Windscreen cracked by a stone"]
    assert "Door dent" in run("TST-002") and "Windscreen cracked by a stone" not in run("TST-002")
    assert run("ranger") and all(d == "Door dent" or d == "Scratch" for d in run("ranger"))
