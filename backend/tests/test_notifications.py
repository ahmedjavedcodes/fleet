"""Notifications: the incident trigger, per-user scoping of the API, and mark-as-read."""

import uuid
from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.enums import NotificationType, UserRole
from app.models.notification import Notification
from app.models.organization import Organization
from app.services import notification_service
from tests.conftest import auth_headers, make_driver, make_user, make_vehicle


def _report_incident(client: TestClient, reporter, vehicle, driver, severity: str = "minor", description: str = "Scratch") -> dict:
    response = client.post(
        "/api/v1/incidents",
        json={
            "vehicle_id": str(vehicle.id),
            "driver_id": str(driver.id),
            "incident_type": "damage",
            "date": "2026-09-30",
            "severity": severity,
            "description": description,
        },
        headers=auth_headers(reporter),
    )
    assert response.status_code == 201, response.text
    return response.json()


def _notifications_for(db: Session, user) -> list[Notification]:
    db.expire_all()
    return list(db.execute(select(Notification).where(Notification.user_id == user.id)).scalars())


@pytest.fixture()
def fleet(db_session: Session, organization: Organization):
    """An org with staff of every role plus a driver who can report incidents."""
    driver_user = make_user(db_session, organization, role=UserRole.driver)
    return {
        "admin": make_user(db_session, organization, role=UserRole.admin),
        "fm1": make_user(db_session, organization, role=UserRole.fleet_manager),
        "fm2": make_user(db_session, organization, role=UserRole.fleet_manager),
        "mechanic": make_user(db_session, organization, role=UserRole.mechanic),
        "driver_user": driver_user,
        "driver": make_driver(db_session, organization, user=driver_user, full_name="Ali Khan"),
        "vehicle": make_vehicle(db_session, organization, plate_number="AB-1234"),
    }


# --- Incident trigger -------------------------------------------------------------


def test_incident_notifies_every_admin_and_fleet_manager_in_the_organization(
    client: TestClient, db_session: Session, fleet
) -> None:
    _report_incident(client, fleet["driver_user"], fleet["vehicle"], fleet["driver"])

    for role in ("admin", "fm1", "fm2"):
        rows = _notifications_for(db_session, fleet[role])
        assert len(rows) == 1, role
        assert rows[0].is_read is False
        assert "AB-1234" in rows[0].title
        assert "Scratch" in rows[0].message
        assert "Ali Khan" in rows[0].message


def test_incident_does_not_notify_drivers_or_mechanics(client: TestClient, db_session: Session, fleet) -> None:
    _report_incident(client, fleet["driver_user"], fleet["vehicle"], fleet["driver"])

    assert _notifications_for(db_session, fleet["driver_user"]) == []
    assert _notifications_for(db_session, fleet["mechanic"]) == []


def test_incident_does_not_notify_other_organizations_or_inactive_users(
    client: TestClient, db_session: Session, organization: Organization, fleet
) -> None:
    other_org = Organization(id=uuid.uuid4(), name="Other Co", slug=f"other-{uuid.uuid4().hex[:8]}")
    db_session.add(other_org)
    db_session.commit()
    outsider = make_user(db_session, other_org, role=UserRole.admin)
    retired = make_user(db_session, organization, role=UserRole.fleet_manager, is_active=False)

    _report_incident(client, fleet["driver_user"], fleet["vehicle"], fleet["driver"])

    assert _notifications_for(db_session, outsider) == []
    assert _notifications_for(db_session, retired) == []


def test_severe_and_critical_incidents_are_warnings_and_lesser_ones_are_events(
    client: TestClient, db_session: Session, fleet
) -> None:
    for severity in ("minor", "moderate", "severe", "critical"):
        _report_incident(client, fleet["driver_user"], fleet["vehicle"], fleet["driver"], severity=severity, description=severity)

    by_text = {n.message.split(" (")[0]: n.type for n in _notifications_for(db_session, fleet["admin"])}
    assert by_text == {
        "minor": NotificationType.event,
        "moderate": NotificationType.event,
        "severe": NotificationType.warning,
        "critical": NotificationType.warning,
    }


def test_a_notification_failure_never_blocks_the_incident_report(
    client: TestClient, db_session: Session, fleet, monkeypatch: pytest.MonkeyPatch
) -> None:
    def boom(*args, **kwargs):
        raise RuntimeError("notification store is down")

    monkeypatch.setattr(notification_service, "notify_roles", boom)

    incident = _report_incident(client, fleet["driver_user"], fleet["vehicle"], fleet["driver"])

    assert client.get(f"/api/v1/incidents/{incident['id']}", headers=auth_headers(fleet["admin"])).status_code == 200
    assert _notifications_for(db_session, fleet["admin"]) == []


# --- GET /notifications -----------------------------------------------------------


def test_list_returns_only_the_callers_own_notifications(client: TestClient, db_session: Session, fleet) -> None:
    _report_incident(client, fleet["driver_user"], fleet["vehicle"], fleet["driver"])
    db_session.add(
        Notification(id=uuid.uuid4(), user_id=fleet["driver_user"].id, title="Only for the driver", message="hi", type=NotificationType.event)
    )
    db_session.commit()

    admin_rows = client.get("/api/v1/notifications", headers=auth_headers(fleet["admin"])).json()
    driver_rows = client.get("/api/v1/notifications", headers=auth_headers(fleet["driver_user"])).json()

    assert [r["title"] for r in driver_rows] == ["Only for the driver"]
    assert len(admin_rows) == 1
    assert "Only for the driver" not in [r["title"] for r in admin_rows]
    assert set(admin_rows[0]) == {"id", "title", "message", "type", "is_read", "created_at"}


def test_list_supports_type_and_unread_filters_and_is_newest_first(client: TestClient, db_session: Session, fleet) -> None:
    admin = fleet["admin"]
    # Explicit timestamps: the test transaction makes server-side now() identical for every row.
    for minute, (title, kind) in enumerate((("first", "event"), ("second", "warning"), ("third", "event"))):
        db_session.add(
            Notification(
                id=uuid.uuid4(),
                user_id=admin.id,
                title=title,
                message=title,
                type=NotificationType(kind),
                created_at=datetime(2026, 9, 30, 9, minute, tzinfo=timezone.utc),
            )
        )
    db_session.commit()

    headers = auth_headers(admin)
    assert [r["title"] for r in client.get("/api/v1/notifications", headers=headers).json()] == ["third", "second", "first"]
    assert [r["title"] for r in client.get("/api/v1/notifications", params={"type": "warning"}, headers=headers).json()] == ["second"]

    first = client.get("/api/v1/notifications", params={"type": "event"}, headers=headers).json()[-1]
    client.patch(f"/api/v1/notifications/{first['id']}/read", headers=headers)
    unread = client.get("/api/v1/notifications", params={"unread_only": True}, headers=headers).json()
    assert {r["title"] for r in unread} == {"second", "third"}


@pytest.mark.parametrize("role", [UserRole.admin, UserRole.fleet_manager, UserRole.driver, UserRole.mechanic])
def test_every_role_can_list_its_own_notifications(client: TestClient, db_session: Session, organization: Organization, role) -> None:
    user = make_user(db_session, organization, role=role)
    assert client.get("/api/v1/notifications", headers=auth_headers(user)).status_code == 200


def test_list_requires_authentication(client: TestClient) -> None:
    assert client.get("/api/v1/notifications").status_code in (401, 403)


# --- PATCH /notifications/{id}/read -----------------------------------------------


def test_mark_read_flips_is_read_and_is_idempotent(client: TestClient, db_session: Session, fleet) -> None:
    _report_incident(client, fleet["driver_user"], fleet["vehicle"], fleet["driver"])
    headers = auth_headers(fleet["admin"])
    notification = client.get("/api/v1/notifications", headers=headers).json()[0]
    assert notification["is_read"] is False

    first = client.patch(f"/api/v1/notifications/{notification['id']}/read", headers=headers)
    again = client.patch(f"/api/v1/notifications/{notification['id']}/read", headers=headers)

    assert first.status_code == again.status_code == 200
    assert first.json()["is_read"] is True and again.json()["is_read"] is True
    assert client.get("/api/v1/notifications", headers=headers).json()[0]["is_read"] is True


def test_cannot_mark_another_users_notification_read(client: TestClient, db_session: Session, fleet) -> None:
    _report_incident(client, fleet["driver_user"], fleet["vehicle"], fleet["driver"])
    admins_notification = client.get("/api/v1/notifications", headers=auth_headers(fleet["admin"])).json()[0]

    response = client.patch(f"/api/v1/notifications/{admins_notification['id']}/read", headers=auth_headers(fleet["fm1"]))

    assert response.status_code == 404
    assert client.get("/api/v1/notifications", headers=auth_headers(fleet["admin"])).json()[0]["is_read"] is False


def test_mark_read_unknown_id_is_404(client: TestClient, fleet) -> None:
    response = client.patch(f"/api/v1/notifications/{uuid.uuid4()}/read", headers=auth_headers(fleet["admin"]))
    assert response.status_code == 404
