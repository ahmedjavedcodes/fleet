import uuid
from datetime import date, timedelta
from decimal import Decimal

import pytest
from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.models.enums import PurchaseOrderStatus, UserRole
from app.models.organization import Organization
from app.models.user import User
from app.schemas.inventory import PurchaseOrderCreate, PurchaseOrderLineItem, PurchaseOrderUpdate
from app.services import purchase_order_service
from tests.conftest import make_part, make_supplier, make_user

TODAY = date(2026, 9, 17)


@pytest.fixture()
def admin(db_session: Session, organization: Organization) -> User:
    return make_user(db_session, organization, role=UserRole.admin)


def _create(db_session: Session, org: Organization, admin: User, supplier, *parts, expected_delivery=None):
    line_items = [PurchaseOrderLineItem(part_id=p.id, qty=10, unit_price=Decimal("5.00")) for p in parts]
    data = PurchaseOrderCreate(
        supplier_id=supplier.id,
        order_date=TODAY,
        expected_delivery=expected_delivery or TODAY,
        line_items=line_items,
    )
    return purchase_order_service.create_purchase_order(db_session, org.id, data, admin.id)


def test_create_purchase_order_computes_total_cost(db_session: Session, organization: Organization, admin: User) -> None:
    supplier = make_supplier(db_session, organization)
    part = make_part(db_session, organization)
    order = _create(db_session, organization, admin, supplier, part)
    assert order.total_cost == Decimal("50.00")  # 10 * 5.00
    assert order.status == PurchaseOrderStatus.pending


def test_receive_sets_actual_delivery_and_status(db_session: Session, organization: Organization, admin: User) -> None:
    supplier = make_supplier(db_session, organization)
    part = make_part(db_session, organization, qty_on_hand=0)
    order = _create(db_session, organization, admin, supplier, part)

    response = purchase_order_service.receive_purchase_order(db_session, organization.id, order.id, admin.id)
    assert response.order.status == PurchaseOrderStatus.received
    assert response.order.actual_delivery is not None


def test_receive_increments_all_line_items(db_session: Session, organization: Organization, admin: User) -> None:
    supplier = make_supplier(db_session, organization)
    part_a = make_part(db_session, organization, qty_on_hand=5)
    part_b = make_part(db_session, organization, qty_on_hand=0)
    order = _create(db_session, organization, admin, supplier, part_a, part_b)

    response = purchase_order_service.receive_purchase_order(db_session, organization.id, order.id, admin.id)

    db_session.refresh(part_a)
    db_session.refresh(part_b)
    assert part_a.qty_on_hand == 15
    assert part_b.qty_on_hand == 10
    assert {u.part_id: u.new_qty for u in response.stock_updates} == {part_a.id: 15, part_b.id: 10}


def test_receive_rejects_already_received_order(db_session: Session, organization: Organization, admin: User) -> None:
    supplier = make_supplier(db_session, organization)
    part = make_part(db_session, organization)
    order = _create(db_session, organization, admin, supplier, part)
    purchase_order_service.receive_purchase_order(db_session, organization.id, order.id, admin.id)

    with pytest.raises(HTTPException) as exc_info:
        purchase_order_service.receive_purchase_order(db_session, organization.id, order.id, admin.id)
    assert exc_info.value.status_code == 409


def test_purchase_order_immutable_after_receive(db_session: Session, organization: Organization, admin: User) -> None:
    supplier = make_supplier(db_session, organization)
    part = make_part(db_session, organization)
    order = _create(db_session, organization, admin, supplier, part)
    purchase_order_service.receive_purchase_order(db_session, organization.id, order.id, admin.id)

    with pytest.raises(HTTPException) as exc_info:
        purchase_order_service.update_purchase_order(
            db_session, organization.id, order.id, PurchaseOrderUpdate(expected_delivery=TODAY), admin.id
        )
    assert exc_info.value.status_code == 409


def test_update_purchase_order_cannot_set_status_received_directly(
    db_session: Session, organization: Organization, admin: User
) -> None:
    """Receiving only ever happens through receive_purchase_order, which runs
    the stock/reliability side effects -- a plain field update must not be able
    to sneak an order into 'received' status without them."""
    supplier = make_supplier(db_session, organization)
    part = make_part(db_session, organization)
    order = _create(db_session, organization, admin, supplier, part)

    with pytest.raises(HTTPException) as exc_info:
        purchase_order_service.update_purchase_order(
            db_session, organization.id, order.id, PurchaseOrderUpdate(status=PurchaseOrderStatus.received), admin.id
        )
    assert exc_info.value.status_code == 400


def test_update_purchase_order_recomputes_total_cost_on_line_items_change(
    db_session: Session, organization: Organization, admin: User
) -> None:
    supplier = make_supplier(db_session, organization)
    part = make_part(db_session, organization)
    order = _create(db_session, organization, admin, supplier, part)

    updated = purchase_order_service.update_purchase_order(
        db_session,
        organization.id,
        order.id,
        PurchaseOrderUpdate(line_items=[PurchaseOrderLineItem(part_id=part.id, qty=4, unit_price=Decimal("9.00"))]),
        admin.id,
    )
    assert updated.total_cost == Decimal("36.00")


def test_list_purchase_orders_filters(db_session: Session, organization: Organization, admin: User) -> None:
    supplier_a = make_supplier(db_session, organization)
    supplier_b = make_supplier(db_session, organization)
    part = make_part(db_session, organization, qty_on_hand=100)
    order_a = _create(db_session, organization, admin, supplier_a, part, expected_delivery=TODAY)
    _create(db_session, organization, admin, supplier_b, part, expected_delivery=TODAY + timedelta(days=5))
    purchase_order_service.receive_purchase_order(db_session, organization.id, order_a.id, admin.id)

    by_status = purchase_order_service.list_purchase_orders(db_session, organization.id, status=PurchaseOrderStatus.received)
    assert len(by_status) == 1
    assert by_status[0].id == order_a.id

    by_supplier = purchase_order_service.list_purchase_orders(db_session, organization.id, supplier_id=supplier_b.id)
    assert len(by_supplier) == 1
    assert by_supplier[0].supplier_id == supplier_b.id


# --- Supplier reliability scoring (exercised only via receive, per the plan) ---


def test_reliability_score_null_until_first_receive(db_session: Session, organization: Organization) -> None:
    supplier = make_supplier(db_session, organization)
    assert supplier.reliability_score is None


def test_reliability_score_on_time_ratio(db_session: Session, organization: Organization, admin: User) -> None:
    supplier = make_supplier(db_session, organization)
    part = make_part(db_session, organization, qty_on_hand=100)

    on_time_order = _create(db_session, organization, admin, supplier, part, expected_delivery=TODAY + timedelta(days=5))
    late_order = _create(db_session, organization, admin, supplier, part, expected_delivery=TODAY - timedelta(days=100))

    purchase_order_service.receive_purchase_order(db_session, organization.id, on_time_order.id, admin.id)
    purchase_order_service.receive_purchase_order(db_session, organization.id, late_order.id, admin.id)

    db_session.refresh(supplier)
    assert supplier.reliability_score == Decimal("0.500")


def test_reliability_score_recalculated_fresh_each_receive(
    db_session: Session, organization: Organization, admin: User
) -> None:
    supplier = make_supplier(db_session, organization)
    part = make_part(db_session, organization, qty_on_hand=100)

    order1 = _create(db_session, organization, admin, supplier, part, expected_delivery=TODAY + timedelta(days=5))
    purchase_order_service.receive_purchase_order(db_session, organization.id, order1.id, admin.id)
    db_session.refresh(supplier)
    assert supplier.reliability_score == Decimal("1.000")

    order2 = _create(db_session, organization, admin, supplier, part, expected_delivery=TODAY - timedelta(days=100))
    purchase_order_service.receive_purchase_order(db_session, organization.id, order2.id, admin.id)
    db_session.refresh(supplier)
    assert supplier.reliability_score == Decimal("0.500")


def test_transaction_rollback_on_reliability_step_failure(
    db_session: Session, organization: Organization, admin: User, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Forces the reliability-score step to fail after stock has already been
    incremented in-session, and asserts neither survives -- receive is genuinely
    one transaction, not two sequential ones."""
    supplier = make_supplier(db_session, organization)
    part = make_part(db_session, organization, qty_on_hand=5)
    order = _create(db_session, organization, admin, supplier, part)

    from app.services import supplier_service

    def _boom(db, org_id, supplier_id):
        raise RuntimeError("simulated reliability-score failure")

    monkeypatch.setattr(supplier_service, "_recalculate_reliability_score", _boom)

    with pytest.raises(RuntimeError):
        purchase_order_service.receive_purchase_order(db_session, organization.id, order.id, admin.id)

    monkeypatch.undo()
    db_session.rollback()

    db_session.refresh(part)
    db_session.refresh(order)
    assert part.qty_on_hand == 5  # unchanged -- increment was never committed
    assert order.status == PurchaseOrderStatus.pending  # unchanged


def test_purchase_order_org_scoping(db_session: Session, organization: Organization, admin: User) -> None:
    supplier = make_supplier(db_session, organization)
    part = make_part(db_session, organization)
    _create(db_session, organization, admin, supplier, part)

    other_org = Organization(id=uuid.uuid4(), name="Other Co", slug=f"other-{uuid.uuid4().hex[:8]}")
    db_session.add(other_org)
    db_session.commit()

    assert purchase_order_service.list_purchase_orders(db_session, other_org.id) == []
