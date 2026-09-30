import uuid
from datetime import date, timedelta
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.models.enums import UserRole
from app.models.organization import Organization
from tests.conftest import auth_headers, make_part, make_supplier, make_user

TODAY = date(2026, 9, 17)


@pytest.fixture()
def admin(db_session: Session, organization: Organization):
    return make_user(db_session, organization, role=UserRole.admin)


def _part_payload(**overrides) -> dict:
    payload = {
        "part_number": f"PN-{uuid.uuid4().hex[:8]}",
        "name": "Alternator Belt",
        "category": "belts",
        "compatible_vehicles": [{"make": "Toyota", "model": "Hilux"}],
        "reorder_threshold": 5,
        "unit_cost": "25.00",
        "qty_on_hand": 10,
    }
    payload.update(overrides)
    return payload


def _po_payload(supplier_id, part_id, **overrides) -> dict:
    payload = {
        "supplier_id": str(supplier_id),
        "order_date": str(TODAY),
        "expected_delivery": str(TODAY),
        "line_items": [{"part_id": str(part_id), "qty": 10, "unit_price": "5.00"}],
    }
    payload.update(overrides)
    return payload


# --- RBAC matrix: inventory router ------------------------------------------------


@pytest.mark.parametrize("role", [UserRole.admin, UserRole.fleet_manager])
def test_inventory_write_allowed_for_admin_and_fleet_manager(
    client: TestClient, db_session: Session, organization: Organization, role: UserRole
) -> None:
    user = make_user(db_session, organization, role=role)
    response = client.post("/api/v1/inventory", json=_part_payload(), headers=auth_headers(user))
    assert response.status_code == 201


@pytest.mark.parametrize("role", [UserRole.driver, UserRole.mechanic])
def test_inventory_write_forbidden_for_driver_and_mechanic(
    client: TestClient, db_session: Session, organization: Organization, role: UserRole
) -> None:
    user = make_user(db_session, organization, role=role)
    response = client.post("/api/v1/inventory", json=_part_payload(), headers=auth_headers(user))
    assert response.status_code == 403


@pytest.mark.parametrize("role", [UserRole.admin, UserRole.fleet_manager, UserRole.mechanic])
def test_inventory_reads_allowed_for_admin_fleet_manager_mechanic(
    client: TestClient, db_session: Session, organization: Organization, admin, role: UserRole
) -> None:
    client.post("/api/v1/inventory", json=_part_payload(), headers=auth_headers(admin))
    user = make_user(db_session, organization, role=role)
    assert client.get("/api/v1/inventory", headers=auth_headers(user)).status_code == 200
    assert client.get("/api/v1/inventory/low-stock", headers=auth_headers(user)).status_code == 200


def test_inventory_driver_forbidden_on_all_routes(
    client: TestClient, db_session: Session, organization: Organization, admin
) -> None:
    part = client.post("/api/v1/inventory", json=_part_payload(), headers=auth_headers(admin)).json()
    driver = make_user(db_session, organization, role=UserRole.driver)

    assert client.get("/api/v1/inventory", headers=auth_headers(driver)).status_code == 403
    assert client.get("/api/v1/inventory/low-stock", headers=auth_headers(driver)).status_code == 403
    assert client.post("/api/v1/inventory", json=_part_payload(), headers=auth_headers(driver)).status_code == 403
    assert (
        client.put(f"/api/v1/inventory/{part['id']}", json={"name": "x"}, headers=auth_headers(driver)).status_code
        == 403
    )


@pytest.mark.parametrize("role", [UserRole.driver, UserRole.mechanic])
def test_inventory_update_forbidden_for_driver_and_mechanic(
    client: TestClient, db_session: Session, organization: Organization, admin, role: UserRole
) -> None:
    part = client.post("/api/v1/inventory", json=_part_payload(), headers=auth_headers(admin)).json()
    user = make_user(db_session, organization, role=role)
    response = client.put(f"/api/v1/inventory/{part['id']}", json={"name": "Updated"}, headers=auth_headers(user))
    assert response.status_code == 403


# --- Low stock fresh evaluation -----------------------------------------------------


def test_low_stock_returns_exact_matching_items(
    client: TestClient, db_session: Session, organization: Organization, admin
) -> None:
    low = make_part(db_session, organization, qty_on_hand=2, reorder_threshold=5)
    ok = make_part(db_session, organization, qty_on_hand=10, reorder_threshold=5)
    at_threshold = make_part(db_session, organization, qty_on_hand=5, reorder_threshold=5)

    response = client.get("/api/v1/inventory/low-stock", headers=auth_headers(admin))
    assert response.status_code == 200
    body = response.json()
    ids = {item["id"] for item in body}
    assert ids == {str(low.id)}
    assert ok.id not in ids
    assert at_threshold.id not in ids

    low_item = next(item for item in body if item["id"] == str(low.id))
    assert low_item["deficit"] == 3  # reorder_threshold(5) - qty_on_hand(2)


def test_low_stock_reflects_current_state_not_a_cached_flag(
    client: TestClient, db_session: Session, organization: Organization, admin
) -> None:
    part = make_part(db_session, organization, qty_on_hand=2, reorder_threshold=5)
    assert client.get("/api/v1/inventory/low-stock", headers=auth_headers(admin)).json() != []

    # Manually top up stock above the threshold -- low-stock must be evaluated
    # fresh on every call, not cached from an earlier response.
    client.put(f"/api/v1/inventory/{part.id}", json={"qty_on_hand": 20}, headers=auth_headers(admin))
    remaining = client.get("/api/v1/inventory/low-stock", headers=auth_headers(admin)).json()
    assert all(item["id"] != str(part.id) for item in remaining)


# --- Purchase orders: RBAC matrix -----------------------------------------------------


@pytest.mark.parametrize("role", [UserRole.admin, UserRole.fleet_manager])
def test_purchase_order_write_allowed_for_admin_and_fleet_manager(
    client: TestClient, db_session: Session, organization: Organization, role: UserRole
) -> None:
    user = make_user(db_session, organization, role=role)
    supplier = make_supplier(db_session, organization)
    part = make_part(db_session, organization)
    response = client.post("/api/v1/purchase-orders", json=_po_payload(supplier.id, part.id), headers=auth_headers(user))
    assert response.status_code == 201


@pytest.mark.parametrize("role", [UserRole.driver, UserRole.mechanic])
def test_purchase_order_write_forbidden_for_driver_and_mechanic(
    client: TestClient, db_session: Session, organization: Organization, role: UserRole
) -> None:
    user = make_user(db_session, organization, role=role)
    supplier = make_supplier(db_session, organization)
    part = make_part(db_session, organization)
    response = client.post("/api/v1/purchase-orders", json=_po_payload(supplier.id, part.id), headers=auth_headers(user))
    assert response.status_code == 403


def test_purchase_order_driver_forbidden_on_all_routes(
    client: TestClient, db_session: Session, organization: Organization, admin
) -> None:
    supplier = make_supplier(db_session, organization)
    part = make_part(db_session, organization)
    order = client.post(
        "/api/v1/purchase-orders", json=_po_payload(supplier.id, part.id), headers=auth_headers(admin)
    ).json()
    driver = make_user(db_session, organization, role=UserRole.driver)

    assert client.get("/api/v1/purchase-orders", headers=auth_headers(driver)).status_code == 403
    assert client.post(
        "/api/v1/purchase-orders", json=_po_payload(supplier.id, part.id), headers=auth_headers(driver)
    ).status_code == 403
    assert (
        client.put(f"/api/v1/purchase-orders/{order['id']}", json={"expected_delivery": str(TODAY)}, headers=auth_headers(driver)).status_code
        == 403
    )
    assert (
        client.patch(f"/api/v1/purchase-orders/{order['id']}/receive", headers=auth_headers(driver)).status_code == 403
    )


def test_purchase_order_mechanic_reads_allowed_writes_forbidden(
    client: TestClient, db_session: Session, organization: Organization, admin
) -> None:
    supplier = make_supplier(db_session, organization)
    part = make_part(db_session, organization)
    order = client.post(
        "/api/v1/purchase-orders", json=_po_payload(supplier.id, part.id), headers=auth_headers(admin)
    ).json()
    mechanic = make_user(db_session, organization, role=UserRole.mechanic)

    assert client.get("/api/v1/purchase-orders", headers=auth_headers(mechanic)).status_code == 200
    assert (
        client.put(f"/api/v1/purchase-orders/{order['id']}", json={"expected_delivery": str(TODAY)}, headers=auth_headers(mechanic)).status_code
        == 403
    )
    assert (
        client.patch(f"/api/v1/purchase-orders/{order['id']}/receive", headers=auth_headers(mechanic)).status_code
        == 403
    )


# --- Receive side-effects --------------------------------------------------------------


def test_receive_returns_200_increments_stock_and_sets_received(
    client: TestClient, db_session: Session, organization: Organization, admin
) -> None:
    supplier = make_supplier(db_session, organization)
    part = make_part(db_session, organization, qty_on_hand=5)
    order = client.post(
        "/api/v1/purchase-orders", json=_po_payload(supplier.id, part.id), headers=auth_headers(admin)
    ).json()

    response = client.patch(f"/api/v1/purchase-orders/{order['id']}/receive", headers=auth_headers(admin))
    assert response.status_code == 200
    body = response.json()
    assert body["order"]["status"] == "received"
    assert body["order"]["actual_delivery"] is not None
    assert body["stock_updates"] == [{"part_id": str(part.id), "new_qty": 15}]

    part_after = client.get("/api/v1/inventory", headers=auth_headers(admin)).json()
    updated_part = next(p for p in part_after if p["id"] == str(part.id))
    assert updated_part["qty_on_hand"] == 15


# --- PO immutability after receive ------------------------------------------------------


def test_update_purchase_order_after_receive_returns_409(
    client: TestClient, db_session: Session, organization: Organization, admin
) -> None:
    supplier = make_supplier(db_session, organization)
    part = make_part(db_session, organization)
    order = client.post(
        "/api/v1/purchase-orders", json=_po_payload(supplier.id, part.id), headers=auth_headers(admin)
    ).json()
    client.patch(f"/api/v1/purchase-orders/{order['id']}/receive", headers=auth_headers(admin))

    response = client.put(
        f"/api/v1/purchase-orders/{order['id']}", json={"expected_delivery": str(TODAY)}, headers=auth_headers(admin)
    )
    assert response.status_code == 409


def test_receive_already_received_order_returns_409(
    client: TestClient, db_session: Session, organization: Organization, admin
) -> None:
    supplier = make_supplier(db_session, organization)
    part = make_part(db_session, organization)
    order = client.post(
        "/api/v1/purchase-orders", json=_po_payload(supplier.id, part.id), headers=auth_headers(admin)
    ).json()
    client.patch(f"/api/v1/purchase-orders/{order['id']}/receive", headers=auth_headers(admin))

    response = client.patch(f"/api/v1/purchase-orders/{order['id']}/receive", headers=auth_headers(admin))
    assert response.status_code == 409


# --- Multi-tenant isolation --------------------------------------------------------------


@pytest.fixture()
def other_org_admin(db_session: Session):
    other_org = Organization(id=uuid.uuid4(), name="Other Co", slug=f"other-{uuid.uuid4().hex[:8]}")
    db_session.add(other_org)
    db_session.commit()
    return make_user(db_session, other_org, role=UserRole.admin)


def test_cross_tenant_part_access_returns_404(
    client: TestClient, db_session: Session, organization: Organization, admin, other_org_admin
) -> None:
    part = client.post("/api/v1/inventory", json=_part_payload(), headers=auth_headers(admin)).json()
    response = client.put(f"/api/v1/inventory/{part['id']}", json={"name": "hijacked"}, headers=auth_headers(other_org_admin))
    assert response.status_code == 404


def test_cross_tenant_supplier_access_returns_404(
    client: TestClient, db_session: Session, organization: Organization, admin, other_org_admin
) -> None:
    supplier = make_supplier(db_session, organization)
    response = client.put(
        f"/api/v1/suppliers/{supplier.id}", json={"name": "hijacked"}, headers=auth_headers(other_org_admin)
    )
    assert response.status_code == 404


def test_cross_tenant_purchase_order_access_returns_404(
    client: TestClient, db_session: Session, organization: Organization, admin, other_org_admin
) -> None:
    supplier = make_supplier(db_session, organization)
    part = make_part(db_session, organization)
    order = client.post(
        "/api/v1/purchase-orders", json=_po_payload(supplier.id, part.id), headers=auth_headers(admin)
    ).json()

    update_resp = client.put(
        f"/api/v1/purchase-orders/{order['id']}", json={"expected_delivery": str(TODAY)}, headers=auth_headers(other_org_admin)
    )
    assert update_resp.status_code == 404

    receive_resp = client.patch(f"/api/v1/purchase-orders/{order['id']}/receive", headers=auth_headers(other_org_admin))
    assert receive_resp.status_code == 404


def test_cross_tenant_inventory_list_never_leaks(
    client: TestClient, db_session: Session, organization: Organization, admin, other_org_admin
) -> None:
    client.post("/api/v1/inventory", json=_part_payload(), headers=auth_headers(admin))
    response = client.get("/api/v1/inventory", headers=auth_headers(other_org_admin))
    assert response.json() == []


def test_receive_updates_supplier_reliability_and_lead_time_in_the_suppliers_list(
    client: TestClient, db_session: Session, organization: Organization, admin
) -> None:
    supplier = make_supplier(db_session, organization)
    part = make_part(db_session, organization, qty_on_hand=5)
    order_date = date.today() - timedelta(days=4)
    order = client.post(
        "/api/v1/purchase-orders",
        json=_po_payload(supplier.id, part.id, order_date=str(order_date), expected_delivery=str(date.today() + timedelta(days=1))),
        headers=auth_headers(admin),
    ).json()

    before = next(s for s in client.get("/api/v1/suppliers", headers=auth_headers(admin)).json() if s["id"] == str(supplier.id))
    assert before["reliability_score"] is None
    assert before["avg_lead_time_days"] is None

    assert client.patch(f"/api/v1/purchase-orders/{order['id']}/receive", headers=auth_headers(admin)).status_code == 200

    after = next(s for s in client.get("/api/v1/suppliers", headers=auth_headers(admin)).json() if s["id"] == str(supplier.id))
    assert Decimal(after["reliability_score"]) == Decimal("1")
    assert after["avg_lead_time_days"] == 4
