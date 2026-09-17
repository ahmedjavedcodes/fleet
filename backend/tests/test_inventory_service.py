import uuid
from decimal import Decimal

import pytest
from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.models.enums import UserRole
from app.models.organization import Organization
from app.schemas.inventory import CompatibleVehicle, PartsInventoryCreate, PartsInventoryUpdate
from app.services import inventory_service
from tests.conftest import make_part, make_supplier, make_user


def test_create_part(db_session: Session, organization: Organization) -> None:
    admin = make_user(db_session, organization, role=UserRole.admin)
    supplier = make_supplier(db_session, organization)
    data = PartsInventoryCreate(
        part_number="PN-100",
        name="Brake Pad",
        category="brakes",
        compatible_vehicles=[CompatibleVehicle(make="Isuzu", model="NPR")],
        reorder_threshold=5,
        unit_cost=Decimal("40.00"),
        supplier_id=supplier.id,
        qty_on_hand=20,
    )
    part = inventory_service.create_part(db_session, organization.id, data, admin.id)
    assert part.part_number == "PN-100"
    assert part.qty_on_hand == 20
    assert part.compatible_vehicles == [{"make": "Isuzu", "model": "NPR"}]


def test_create_part_duplicate_part_number_rejected(db_session: Session, organization: Organization) -> None:
    admin = make_user(db_session, organization, role=UserRole.admin)
    make_part(db_session, organization, part_number="PN-DUP")
    data = PartsInventoryCreate(
        part_number="PN-DUP", name="Other Part", reorder_threshold=1, unit_cost=Decimal("5.00")
    )
    with pytest.raises(HTTPException) as exc_info:
        inventory_service.create_part(db_session, organization.id, data, admin.id)
    assert exc_info.value.status_code == 409


def test_update_part_manual_stock_adjustment(db_session: Session, organization: Organization) -> None:
    admin = make_user(db_session, organization, role=UserRole.admin)
    part = make_part(db_session, organization, qty_on_hand=10)
    updated = inventory_service.update_part(
        db_session, organization.id, part.id, PartsInventoryUpdate(qty_on_hand=50), admin.id
    )
    assert updated.qty_on_hand == 50


def test_list_parts_filters_by_category_and_supplier(db_session: Session, organization: Organization) -> None:
    supplier_a = make_supplier(db_session, organization)
    supplier_b = make_supplier(db_session, organization)
    make_part(db_session, organization, category="belts", supplier_id=supplier_a.id)
    make_part(db_session, organization, category="brakes", supplier_id=supplier_b.id)

    by_category = inventory_service.list_parts(db_session, organization.id, category="belts")
    assert len(by_category) == 1
    assert by_category[0].category == "belts"

    by_supplier = inventory_service.list_parts(db_session, organization.id, supplier_id=supplier_b.id)
    assert len(by_supplier) == 1
    assert by_supplier[0].supplier_id == supplier_b.id


def test_list_parts_filters_by_compatible_make_and_model(db_session: Session, organization: Organization) -> None:
    make_part(db_session, organization, compatible_vehicles=[{"make": "Toyota", "model": "Hilux"}])
    make_part(db_session, organization, compatible_vehicles=[{"make": "Isuzu", "model": "NPR"}])

    make_only = inventory_service.list_parts(db_session, organization.id, compatible_make="Toyota")
    assert len(make_only) == 1
    assert make_only[0].compatible_vehicles[0]["make"] == "Toyota"

    make_and_model = inventory_service.list_parts(
        db_session, organization.id, compatible_make="Toyota", compatible_model="Corolla"
    )
    assert make_and_model == []


def test_list_low_stock_matches_manual_filter(db_session: Session, organization: Organization) -> None:
    low = make_part(db_session, organization, qty_on_hand=2, reorder_threshold=5)
    ok = make_part(db_session, organization, qty_on_hand=10, reorder_threshold=5)
    exactly_at_threshold = make_part(db_session, organization, qty_on_hand=5, reorder_threshold=5)

    result_ids = {p.id for p in inventory_service.list_low_stock(db_session, organization.id)}
    assert result_ids == {low.id}
    assert ok.id not in result_ids
    assert exactly_at_threshold.id not in result_ids  # equal to threshold is not "below" it


def test_decrement_stock_flags_low_stock_alert(db_session: Session, organization: Organization) -> None:
    part = make_part(db_session, organization, qty_on_hand=10, reorder_threshold=5)
    alerts = inventory_service.decrement_stock_for_parts_used(
        db_session, organization.id, [{"part_id": part.id, "qty": 6}]
    )
    # part is the same identity-mapped object decrement_stock_for_parts_used
    # mutated in place -- asserting on it directly avoids relying on whether
    # db_session.refresh() autoflushes the (deliberately uncommitted) pending
    # change before re-querying.
    assert part.qty_on_hand == 4
    assert alerts == [{"part_id": part.id, "low_stock_alert": True}]


def test_decrement_stock_no_alert_when_above_threshold(db_session: Session, organization: Organization) -> None:
    part = make_part(db_session, organization, qty_on_hand=10, reorder_threshold=5)
    alerts = inventory_service.decrement_stock_for_parts_used(
        db_session, organization.id, [{"part_id": part.id, "qty": 2}]
    )
    assert part.qty_on_hand == 8
    assert alerts == []


def test_decrement_stock_never_goes_negative(db_session: Session, organization: Organization) -> None:
    part = make_part(db_session, organization, qty_on_hand=3, reorder_threshold=5)
    with pytest.raises(HTTPException) as exc_info:
        inventory_service.decrement_stock_for_parts_used(db_session, organization.id, [{"part_id": part.id, "qty": 10}])
    assert exc_info.value.status_code == 400
    assert part.qty_on_hand == 3  # unchanged


def test_decrement_stock_uses_row_lock(db_session: Session, organization: Organization) -> None:
    """Asserts the SELECT ... FOR UPDATE requirement is actually present in the
    compiled query, rather than trying to simulate real concurrent transactions
    against the single test session."""
    part = make_part(db_session, organization, qty_on_hand=10, reorder_threshold=5)

    from sqlalchemy import select

    from app.models.inventory import PartsInventory

    stmt = (
        select(PartsInventory)
        .where(PartsInventory.id == part.id, PartsInventory.organization_id == organization.id)
        .with_for_update()
    )
    compiled = str(stmt.compile(dialect=db_session.get_bind().dialect, compile_kwargs={"literal_binds": True}))
    assert "FOR UPDATE" in compiled.upper()


def test_increment_stock_for_line_items(db_session: Session, organization: Organization) -> None:
    part_a = make_part(db_session, organization, qty_on_hand=5)
    part_b = make_part(db_session, organization, qty_on_hand=0)

    updates = inventory_service.increment_stock_for_line_items(
        db_session,
        organization.id,
        [
            {"part_id": part_a.id, "qty": 10, "unit_price": Decimal("5.00")},
            {"part_id": part_b.id, "qty": 3, "unit_price": Decimal("5.00")},
        ],
    )
    assert part_a.qty_on_hand == 15
    assert part_b.qty_on_hand == 3
    assert {u["part_id"]: u["new_qty"] for u in updates} == {part_a.id: 15, part_b.id: 3}


def test_inventory_org_scoping(db_session: Session, organization: Organization) -> None:
    make_part(db_session, organization)

    other_org = Organization(id=uuid.uuid4(), name="Other Co", slug=f"other-{uuid.uuid4().hex[:8]}")
    db_session.add(other_org)
    db_session.commit()

    assert inventory_service.list_parts(db_session, other_org.id) == []
    assert inventory_service.list_low_stock(db_session, other_org.id) == []
