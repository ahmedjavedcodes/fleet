"""The dashboard's aggregation, paging, indexes and the warnings feed, after the seed of ~80,000 rows made the old
load-everything-then-count code unusably slow. Everything here is checked against the behaviour it replaced."""

import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import event, inspect
from sqlalchemy.orm import Session

from app.models.enums import (
    IncidentResolutionStatus,
    IncidentSeverity,
    IncidentType,
    NotificationType,
    ServiceType,
    UserRole,
    VehicleStatus,
)
from app.models.organization import Organization
from app.schemas.accountability import IncidentLogCreate
from app.services import (
    compliance_service,
    dashboard_service,
    fuel_service,
    incident_service,
    inventory_service,
    maintenance_service,
    notification_service,
    supplier_service,
)
from tests.conftest import (
    auth_headers,
    engine,
    make_compliance_rule,
    make_driver,
    make_maintenance_log,
    make_part,
    make_supplier,
    make_user,
    make_vehicle,
)

NOW = datetime.now(timezone.utc).date()


@pytest.fixture()
def admin(db_session: Session, organization: Organization):
    return make_user(db_session, organization, role=UserRole.admin)


def make_incident(db: Session, org: Organization, vehicle, admin, *, severity=IncidentSeverity.minor, status=IncidentResolutionStatus.open, day=None, description="Scratch"):
    incident = incident_service.create_incident(
        db, org.id,
        IncidentLogCreate(vehicle_id=vehicle.id, incident_type=IncidentType.damage, date=day or NOW, severity=severity, description=description),
        admin.id,
    )
    if status != IncidentResolutionStatus.open:
        incident.resolution_status = status
        db.commit()
    return incident


# --- the summary is computed by the database -------------------------------------------------------------------------


def test_the_summary_never_loads_rows_to_count_them(db_session: Session, organization: Organization, admin, monkeypatch: pytest.MonkeyPatch) -> None:
    make_vehicle(db_session, organization)
    make_incident(db_session, organization, make_vehicle(db_session, organization), admin)

    def forbidden(*args, **kwargs):
        raise AssertionError("loaded a whole list to count it")

    monkeypatch.setattr(maintenance_service, "list_overdue", forbidden)
    monkeypatch.setattr(inventory_service, "list_low_stock", forbidden)
    monkeypatch.setattr(incident_service, "list_incidents", forbidden)
    org_id = organization.id
    statements: list[str] = []
    listener = lambda conn, cursor, statement, *rest: statements.append(statement.lower())  # noqa: E731
    event.listen(db_session.get_bind(), "before_cursor_execute", listener)
    try:
        summary = dashboard_service.get_summary(db_session, org_id)
    finally:
        event.remove(db_session.get_bind(), "before_cursor_execute", listener)

    assert summary.open_incidents_count == 1
    assert len(statements) == 7  # vehicles, drivers, fuel, overdue, low stock, incidents, suppliers
    assert all("count(" in s or "sum(" in s for s in statements), statements


def test_the_new_suppliers_figure_counts_live_suppliers_only(db_session: Session, organization: Organization) -> None:
    make_supplier(db_session, organization)
    gone = make_supplier(db_session, organization)
    gone.is_deleted = True
    db_session.commit()

    assert supplier_service.count_active_suppliers(db_session, organization.id) == 1
    assert dashboard_service.get_summary(db_session, organization.id).active_suppliers_count == 1


def test_open_incidents_are_open_plus_investigating_and_nothing_else(db_session: Session, organization: Organization, admin) -> None:
    vehicle = make_vehicle(db_session, organization)
    for status in (IncidentResolutionStatus.open, IncidentResolutionStatus.investigating, IncidentResolutionStatus.resolved, IncidentResolutionStatus.closed):
        make_incident(db_session, organization, vehicle, admin, status=status)

    assert incident_service.count_unresolved(db_session, organization.id) == 2
    assert incident_service.count_unresolved(db_session, organization.id) == len(incident_service.list_incidents(db_session, organization.id, resolution_status=IncidentResolutionStatus.open)) + 1


def test_the_sql_counts_equal_the_list_functions_they_replaced(db_session: Session, organization: Organization) -> None:
    today = NOW
    v1 = make_vehicle(db_session, organization, current_odometer=20_000)
    v2 = make_vehicle(db_session, organization, current_odometer=500)
    v3 = make_vehicle(db_session, organization, current_odometer=14_500)
    make_maintenance_log(db_session, organization, v1, odometer_at_service=1_000, next_due_km=15_000, next_due_date=today + timedelta(days=200))  # overdue by km
    make_maintenance_log(db_session, organization, v2, odometer_at_service=100, next_due_km=90_000, next_due_date=today - timedelta(days=3))  # overdue by date
    make_maintenance_log(db_session, organization, v3, odometer_at_service=1_000, next_due_km=15_000, next_due_date=today + timedelta(days=10))  # due soon, not overdue
    make_maintenance_log(db_session, organization, v2, odometer_at_service=50, next_due_km=1_000, next_due_date=today - timedelta(days=400), date=today - timedelta(days=500))  # superseded
    make_part(db_session, organization, qty_on_hand=1, reorder_threshold=5)
    make_part(db_session, organization, qty_on_hand=9, reorder_threshold=5)

    assert maintenance_service.count_overdue(db_session, organization.id) == len(maintenance_service.list_overdue(db_session, organization.id)) == 2
    assert maintenance_service.overdue_vehicle_ids(db_session, organization.id) == {o.vehicle_id for o in maintenance_service.list_overdue(db_session, organization.id)}
    assert maintenance_service.due_soon_vehicle_ids(db_session, organization.id) == {u.vehicle_id for u in maintenance_service.list_upcoming(db_session, organization.id)}
    assert inventory_service.count_low_stock(db_session, organization.id) == len(inventory_service.list_low_stock(db_session, organization.id)) == 1


def test_month_fuel_cost_matches_the_monthly_summary(db_session: Session, organization: Organization, admin) -> None:
    from app.schemas.fuel import FuelLogCreate

    vehicle = make_vehicle(db_session, organization, current_odometer=0)
    for i, cost in enumerate(("200.00", "300.50")):
        fuel_service.create_fuel_log(
            db_session, organization.id,
            FuelLogCreate(vehicle_id=vehicle.id, date=NOW, odometer_reading=100 * (i + 1), liters_filled=Decimal("10"), price_per_liter=Decimal("20"), total_cost=Decimal(cost)), admin.id,
        )

    assert fuel_service.month_total_cost(db_session, organization.id) == Decimal("500.50") == fuel_service.get_monthly_summary(db_session, organization.id, month=None).total_cost
    assert dashboard_service.get_summary(db_session, organization.id).month_fuel_cost == Decimal("500.50")


# --- the fleet-health batch equals the per-vehicle computation -----------------------------------------------------


def test_the_batched_signals_equal_the_per_vehicle_ones(db_session: Session, organization: Organization, admin) -> None:
    make_compliance_rule(db_session, organization, vehicle_make="Toyota", vehicle_model="Hilux", service_type=ServiceType.oil_change, interval_km=10_000, interval_months=6)
    make_compliance_rule(db_session, organization, vehicle_make="Toyota", vehicle_model="Hilux", service_type=ServiceType.brake_service, interval_km=20_000, interval_months=12)
    fleet = [
        make_vehicle(db_session, organization, make="Toyota", model="Hilux", current_odometer=12_000),
        make_vehicle(db_session, organization, make="Toyota", model="Hilux", current_odometer=500),
        make_vehicle(db_session, organization, make="Isuzu", model="NPR", current_odometer=9_000),
    ]
    make_maintenance_log(db_session, organization, fleet[0], service_type=ServiceType.oil_change, odometer_at_service=1_000, date=NOW - timedelta(days=30))
    make_maintenance_log(db_session, organization, fleet[1], service_type=ServiceType.oil_change, odometer_at_service=400, date=NOW - timedelta(days=300))
    for _ in range(3):
        make_incident(db_session, organization, fleet[0], admin)

    batched = compliance_service.compliance_statuses_by_vehicle(db_session, organization.id, fleet)
    for vehicle in fleet:
        single = compliance_service.get_vehicle_compliance(db_session, organization.id, vehicle.id)
        assert batched[vehicle.id] == [item.status for item in single.items], vehicle.plate_number
    assert incident_service.recent_incident_counts(db_session, organization.id) == {fleet[0].id: 3}
    assert incident_service.count_recent_incidents_for_vehicle(db_session, organization.id, fleet[0].id) == 3
    periods = fuel_service.cost_per_km_periods_by_vehicle(db_session, organization.id)
    for vehicle in fleet:
        assert periods.get(vehicle.id, (None, None)) == fuel_service.get_vehicle_cost_per_km_periods(db_session, organization.id, vehicle.id)


def test_fleet_health_pages_worst_first_with_the_total(db_session: Session, organization: Organization, admin) -> None:
    vehicles = [make_vehicle(db_session, organization, plate_number=f"HLT-{i:03d}") for i in range(6)]
    for i, vehicle in enumerate(vehicles):
        for _ in range(i % 4):  # 0..3 incidents lowers the incident signal
            make_incident(db_session, organization, vehicle, admin)
    retired = make_vehicle(db_session, organization, status=VehicleStatus.retired)

    everything, total = dashboard_service.get_fleet_health_page(db_session, organization.id)
    first, total_first = dashboard_service.get_fleet_health_page(db_session, organization.id, limit=4)
    second, _ = dashboard_service.get_fleet_health_page(db_session, organization.id, limit=4, offset=4)

    assert total == total_first == 6 and len(everything) == 6 and retired.id not in {r.vehicle_id for r in everything}
    assert len(first) == 4 and len(second) == 2
    ordered = first + second
    assert [r.health_score for r in ordered] == sorted(r.health_score for r in everything)
    assert len({r.vehicle_id for r in ordered}) == 6  # no repeats across pages


# --- the maintenance calendar, paged in SQL ------------------------------------------------------------------------


def _calendar_fixture(db: Session, org: Organization):
    plates = []
    for i in range(7):
        vehicle = make_vehicle(db, org, plate_number=f"CAL-{i:03d}", current_odometer=50_000)
        plates.append(vehicle.plate_number)
        if i < 4:  # overdue by date, the oldest due date first
            make_maintenance_log(db, org, vehicle, odometer_at_service=40_000, next_due_km=None, next_due_date=NOW - timedelta(days=10 * (i + 1)))
        elif i < 6:  # due within the window
            make_maintenance_log(db, org, vehicle, odometer_at_service=40_000, next_due_km=None, next_due_date=NOW + timedelta(days=i))
        else:  # far in the future: not on the calendar
            make_maintenance_log(db, org, vehicle, odometer_at_service=40_000, next_due_km=None, next_due_date=NOW + timedelta(days=300))
    return plates


def test_the_calendar_lists_the_latest_due_date_first_and_pages_with_a_total(db_session: Session, organization: Organization) -> None:
    _calendar_fixture(db_session, organization)

    items, total = dashboard_service.get_maintenance_calendar_page(db_session, organization.id, window_days=30)
    first, total_first = dashboard_service.get_maintenance_calendar_page(db_session, organization.id, window_days=30, limit=4)
    rest, _ = dashboard_service.get_maintenance_calendar_page(db_session, organization.id, window_days=30, limit=4, offset=4)

    assert total == total_first == 6 and len(items) == 6
    # Latest due date first: the future ones, then the overdue ones from the most recent back to the oldest.
    assert [i.plate_number for i in items] == ["CAL-005", "CAL-004", "CAL-000", "CAL-001", "CAL-002", "CAL-003"]
    assert [i.status for i in items] == ["upcoming"] * 2 + ["overdue"] * 4
    assert first == items[:4] and rest == items[4:]
    assert dashboard_service.get_maintenance_calendar(db_session, organization.id, 30) == items


def test_an_item_overdue_by_km_is_not_listed_twice(db_session: Session, organization: Organization) -> None:
    vehicle = make_vehicle(db_session, organization, current_odometer=20_000)
    make_maintenance_log(db_session, organization, vehicle, odometer_at_service=1_000, next_due_km=15_000, next_due_date=NOW + timedelta(days=5))

    items, total = dashboard_service.get_maintenance_calendar_page(db_session, organization.id, window_days=30)

    assert total == 1 and [i.status for i in items] == ["overdue"]


# --- routes ----------------------------------------------------------------------------------------------------------


def test_the_paged_routes_return_the_page_and_the_total_in_a_header(client: TestClient, db_session: Session, organization: Organization, admin) -> None:
    _calendar_fixture(db_session, organization)
    headers = auth_headers(admin)

    page = client.get("/api/v1/dashboard/maintenance-calendar?limit=2&offset=1", headers=headers)
    whole = client.get("/api/v1/dashboard/maintenance-calendar", headers=headers)
    health = client.get("/api/v1/dashboard/fleet-health?limit=3", headers=headers)

    assert page.status_code == 200 and len(page.json()) == 2 and page.headers["x-total-count"] == "6"
    assert len(whole.json()) == 6 and whole.headers["x-total-count"] == "6"  # no limit: everything, as before
    assert health.status_code == 200 and len(health.json()) == 3 and health.headers["x-total-count"] == "7"
    for bad in ("limit=0", "limit=201", "offset=-1"):
        assert client.get(f"/api/v1/dashboard/fleet-health?{bad}", headers=headers).status_code == 422


def test_the_summary_route_returns_the_suppliers_count(client: TestClient, db_session: Session, organization: Organization, admin) -> None:
    make_supplier(db_session, organization)
    make_supplier(db_session, organization)

    body = client.get("/api/v1/dashboard/summary", headers=auth_headers(admin)).json()

    assert body["active_suppliers_count"] == 2 and "low_stock_parts_count" in body


# --- indexes ---------------------------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("table", "columns"),
    [
        ("incident_logs", ["organization_id", "resolution_status", "severity"]),
        ("fuel_logs", ["organization_id", "date"]),
        ("fuel_logs", ["vehicle_id", "date"]),
        ("maintenance_logs", ["organization_id", "date"]),
        ("maintenance_logs", ["vehicle_id", "date"]),
        ("maintenance_logs", ["organization_id", "next_due_date"]),
    ],
)
def test_the_filter_columns_are_indexed(table, columns) -> None:
    indexed = [ix["column_names"] for ix in inspect(engine).get_indexes(table)]
    assert columns in indexed


# --- the warnings feed -----------------------------------------------------------------------------------------------


def test_open_severe_and_critical_incidents_are_warnings_even_with_no_stored_notification(db_session: Session, organization: Organization, admin) -> None:
    vehicle = make_vehicle(db_session, organization, plate_number="WRN-001")
    make_incident(db_session, organization, vehicle, admin, severity=IncidentSeverity.severe, description="Rolled over on the motorway")
    make_incident(db_session, organization, vehicle, admin, severity=IncidentSeverity.critical, status=IncidentResolutionStatus.investigating)
    make_incident(db_session, organization, vehicle, admin, severity=IncidentSeverity.minor)
    make_incident(db_session, organization, vehicle, admin, severity=IncidentSeverity.severe, status=IncidentResolutionStatus.resolved)  # done: not a warning
    assert notification_service.list_notifications(db_session, admin) == []  # nothing was ever stored

    warnings = notification_service.list_feed(db_session, admin, type=NotificationType.warning)

    assert sorted(w.title for w in warnings) == ["Open critical incident on WRN-001", "Open severe incident on WRN-001"]
    first = next(w for w in warnings if "severe" in w.title)
    assert first.type == NotificationType.warning and first.source == "incident" and first.incident_id == first.id
    assert first.is_read is True and "Rolled over on the motorway" in first.message


def test_minor_and_moderate_open_incidents_are_events_and_every_open_incident_is_somewhere(db_session: Session, organization: Organization, admin) -> None:
    vehicle = make_vehicle(db_session, organization)
    for severity in (IncidentSeverity.minor, IncidentSeverity.moderate, IncidentSeverity.severe, IncidentSeverity.critical):
        make_incident(db_session, organization, vehicle, admin, severity=severity)

    events = notification_service.list_feed(db_session, admin, type=NotificationType.event)
    warnings = notification_service.list_feed(db_session, admin, type=NotificationType.warning)
    everything = notification_service.list_feed(db_session, admin)

    assert len(events) == 2 and len(warnings) == 2 and len(everything) == 4
    assert len(everything) == incident_service.count_unresolved(db_session, organization.id)  # the dashboard's "open incidents"


def test_the_feed_is_newest_first_and_pages(db_session: Session, organization: Organization, admin) -> None:
    vehicle = make_vehicle(db_session, organization)
    for i in range(7):
        make_incident(db_session, organization, vehicle, admin, severity=IncidentSeverity.severe, day=NOW - timedelta(days=i), description=f"Incident {i}")

    page_one = notification_service.list_feed(db_session, admin, type=NotificationType.warning, limit=3)
    page_two = notification_service.list_feed(db_session, admin, type=NotificationType.warning, limit=3, offset=3)
    last = notification_service.list_feed(db_session, admin, type=NotificationType.warning, limit=3, offset=6)

    assert [len(page_one), len(page_two), len(last)] == [3, 3, 1]
    stamps = [n.created_at for n in page_one + page_two + last]
    assert stamps == sorted(stamps, reverse=True) and len({n.id for n in page_one + page_two + last}) == 7


def test_stored_notifications_and_derived_ones_are_merged(db_session: Session, organization: Organization, admin) -> None:
    vehicle = make_vehicle(db_session, organization)
    stored = notification_service.notify_roles(db_session, organization.id, [UserRole.admin], title="Stored warning", message="x", type=NotificationType.warning)
    make_incident(db_session, organization, vehicle, admin, severity=IncidentSeverity.critical)

    feed = notification_service.list_feed(db_session, admin, type=NotificationType.warning)

    assert {n.source for n in feed} == {"notification", "incident"} and stored[0].id in {n.id for n in feed}
    assert notification_service.list_feed(db_session, admin, type=NotificationType.warning, unread_only=True) == [
        n for n in feed if n.source == "notification" and not n.is_read
    ]


def test_only_admins_and_fleet_managers_see_incident_warnings(client: TestClient, db_session: Session, organization: Organization, admin) -> None:
    make_incident(db_session, organization, make_vehicle(db_session, organization), admin, severity=IncidentSeverity.severe)
    manager = make_user(db_session, organization, role=UserRole.fleet_manager)
    driver_user = make_user(db_session, organization, role=UserRole.driver)

    seen = {role: client.get("/api/v1/notifications?type=warning", headers=auth_headers(user)).json() for role, user in (("admin", admin), ("manager", manager), ("driver", driver_user))}

    assert len(seen["admin"]) == 1 and len(seen["manager"]) == 1 and seen["driver"] == []
    assert seen["admin"][0]["source"] == "incident" and seen["admin"][0]["type"] == "warning"


def test_an_incident_entry_cannot_be_marked_read_and_another_orgs_incidents_never_appear(client: TestClient, db_session: Session, organization: Organization, admin) -> None:
    incident = make_incident(db_session, organization, make_vehicle(db_session, organization), admin, severity=IncidentSeverity.severe)
    assert client.patch(f"/api/v1/notifications/{incident.id}/read", headers=auth_headers(admin)).status_code == 404

    other_org = Organization(id=uuid.uuid4(), name="Other Co", slug=f"other-{uuid.uuid4().hex[:8]}")
    db_session.add(other_org)
    db_session.commit()
    other_admin = make_user(db_session, other_org, role=UserRole.admin)
    assert client.get("/api/v1/notifications", headers=auth_headers(other_admin)).json() == []


def test_the_feed_route_accepts_an_offset(client: TestClient, db_session: Session, organization: Organization, admin) -> None:
    vehicle = make_vehicle(db_session, organization)
    for i in range(4):
        make_incident(db_session, organization, vehicle, admin, severity=IncidentSeverity.critical, day=NOW - timedelta(days=i))

    first = client.get("/api/v1/notifications?type=warning&limit=3", headers=auth_headers(admin)).json()
    second = client.get("/api/v1/notifications?type=warning&limit=3&offset=3", headers=auth_headers(admin)).json()

    assert len(first) == 3 and len(second) == 1 and not {n["id"] for n in first} & {n["id"] for n in second}
    assert client.get("/api/v1/notifications?offset=-1", headers=auth_headers(admin)).status_code == 422


def test_an_incident_reported_through_the_api_is_listed_once_not_twice(client: TestClient, db_session: Session, organization: Organization, admin) -> None:
    vehicle, driver = make_vehicle(db_session, organization, plate_number="DUP-001"), make_driver(db_session, organization)
    reported = client.post(
        "/api/v1/incidents",
        json={"vehicle_id": str(vehicle.id), "driver_id": str(driver.id), "incident_type": "damage", "date": NOW.isoformat(), "severity": "severe", "description": "Collision"},
        headers=auth_headers(admin),
    ).json()
    elsewhere = make_incident(db_session, organization, vehicle, admin, severity=IncidentSeverity.severe, description="Loaded some other way")

    feed = client.get("/api/v1/notifications?type=warning", headers=auth_headers(admin)).json()

    assert len(feed) == 2
    sources = {n["source"]: n for n in feed}
    assert sources["notification"]["title"].startswith("New severe incident")  # the stored one, with its read state
    assert sources["incident"]["incident_id"] == str(elsewhere.id) and reported["id"] != str(elsewhere.id)
