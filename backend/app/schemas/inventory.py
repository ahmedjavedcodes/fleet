import uuid
from datetime import date as date_type
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field

from app.models.enums import PurchaseOrderStatus

# Note: Supplier schemas (SupplierCreate/Update/Response) already exist in
# app/schemas/supplier.py, built during the Foundation layer and wired into
# app/api/suppliers.py -- reliability_score is already Decimal | None there,
# matching this spec exactly. They are not redefined here to avoid two
# diverging schemas for the same entity; import from app.schemas.supplier
# wherever this module's callers need them.

# --- PartsInventory ------------------------------------------------------------


class CompatibleVehicle(BaseModel):
    make: str
    model: str


class PartsInventoryBase(BaseModel):
    part_number: str
    name: str
    category: str | None = None
    compatible_vehicles: list[CompatibleVehicle] = Field(default_factory=list)
    reorder_threshold: int = Field(ge=0)
    unit_cost: Decimal = Field(gt=0)
    supplier_id: uuid.UUID | None = None


class PartsInventoryCreate(PartsInventoryBase):
    model_config = ConfigDict(extra="forbid")

    qty_on_hand: int = Field(default=0, ge=0)


class PartsInventoryUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    part_number: str | None = None
    name: str | None = None
    category: str | None = None
    compatible_vehicles: list[CompatibleVehicle] | None = None
    reorder_threshold: int | None = Field(default=None, ge=0)
    unit_cost: Decimal | None = Field(default=None, gt=0)
    supplier_id: uuid.UUID | None = None
    # Manual stock adjustment is the one direct write path to qty_on_hand --
    # every other mutation goes through decrement/increment_stock_* below.
    qty_on_hand: int | None = Field(default=None, ge=0)


class PartsInventoryResponse(PartsInventoryBase):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    organization_id: uuid.UUID
    qty_on_hand: int


class LowStockResponse(PartsInventoryResponse):
    deficit: int


# --- PurchaseOrder ---------------------------------------------------------------


class PurchaseOrderLineItem(BaseModel):
    model_config = ConfigDict(extra="forbid")

    part_id: uuid.UUID
    qty: int = Field(gt=0)
    unit_price: Decimal = Field(gt=0)


class PurchaseOrderCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    supplier_id: uuid.UUID
    order_date: date_type
    expected_delivery: date_type
    line_items: list[PurchaseOrderLineItem] = Field(min_length=1)


class PurchaseOrderUpdate(BaseModel):
    """Only pre-receive fields are editable. status here is restricted to
    transitions other than 'received' -- receiving happens exclusively through
    the dedicated /receive endpoint, which also runs the stock/reliability
    side effects that a plain field update must never trigger."""

    model_config = ConfigDict(extra="forbid")

    expected_delivery: date_type | None = None
    line_items: list[PurchaseOrderLineItem] | None = None
    status: PurchaseOrderStatus | None = None


class PurchaseOrderResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    organization_id: uuid.UUID
    supplier_id: uuid.UUID
    order_date: date_type
    expected_delivery: date_type
    actual_delivery: date_type | None
    status: PurchaseOrderStatus
    total_cost: Decimal
    line_items: list[PurchaseOrderLineItem]


class StockUpdate(BaseModel):
    part_id: uuid.UUID
    new_qty: int


class PurchaseOrderReceiveResponse(BaseModel):
    order: PurchaseOrderResponse
    stock_updates: list[StockUpdate]
