# Plan 02 — Unpredictable Spare Parts

**Problem source:** [`backendPlan.md`](../backendPlan.md#problem-2--unpredictable-spare-parts) § Problem 2
**Module conventions:** [`backend/CLAUDE.md`](../CLAUDE.md)

**One-line goal:** three deterministic mechanisms — stock threshold alerts on write, consumption linkage via `MechanicReport.parts_used`, and supplier reliability scoring on receive — all as synchronous, single-transaction side effects.

---

## 0. Prerequisites

- Foundation models (`Organization`, `User`, `Vehicle`) and mixins.
- `Supplier` (Tier 2) must exist before `PartsInventory` and `PurchaseOrder` (both FK to it).
- **Cross-dependency on Plan 03:** `MechanicReport.parts_used` is the consumption event that decrements stock (step 3 below). If Plan 03 (`MaintenanceLog`/`MechanicReport`) hasn't been built yet, build at minimum the `MechanicReport` model and its creation endpoint stub before wiring the decrement side effect — or sequence Plan 03 before this plan's §3.2. Recommended build order: **Plan 01 → Plan 03 (models only) → Plan 02 → finish Plan 03 routes.** If that's too disruptive, build `PartsInventory`/`Supplier`/`PurchaseOrder` fully here and land the decrement hook as a small addition when Plan 03's `MechanicReport` creation endpoint is built.

---

## 1. Models — `app/models/inventory.py`

### `Supplier` (Tier 2 — org-level entity, not scoped to a single problem, but built here since Problem 2 is its only consumer)

| Field | Type | Notes |
|---|---|---|
| `id` | `UUID` (pk) | |
| `name` | `str` | required |
| `contact_email` | `str`, nullable | |
| `phone` | `str`, nullable | |
| `avg_lead_time_days` | `int`, nullable | manually entered, informational |
| `reliability_score` | `numeric(4,3)`, nullable | **computed at write-time on each PurchaseOrder receive**, null until first completed order |
| + `AuditMixin`, `OrgScopedMixin` | | |

### `PartsInventory`

| Field | Type | Notes |
|---|---|---|
| `id` | `UUID` (pk) | |
| `supplier_id` | `UUID` FK → `suppliers.id`, nullable | primary/default supplier |
| `part_number` | `str` | unique per org |
| `name` | `str` | |
| `category` | `str`, nullable | |
| `compatible_vehicles` | `JSONB` | array of `{make, model}` — not normalized, per plan's JSONB tradeoff |
| `qty_on_hand` | `int` default `0` | **mutated by side effects only** — never a direct arbitrary overwrite except via `PUT` manual adjustment |
| `reorder_threshold` | `int` | required |
| `unit_cost` | `numeric(10,2)` | |
| + `AuditMixin`, `OrgScopedMixin` | | |

### `PurchaseOrder`

| Field | Type | Notes |
|---|---|---|
| `id` | `UUID` (pk) | |
| `supplier_id` | `UUID` FK → `suppliers.id` | required |
| `order_date` | `date` | required |
| `expected_delivery` | `date` | required |
| `actual_delivery` | `date`, nullable | set on receive |
| `status` | `enum(pending, shipped, received, cancelled)` default `pending` | |
| `total_cost` | `numeric(12,2)` | computed from `line_items` on create, or entered directly — decide once and document |
| `line_items` | `JSONB` | array of `{part_id, qty, unit_price}` |
| + `AuditMixin`, `OrgScopedMixin` | | |

**Migration order:** `suppliers` → `parts_inventory` → `purchase_orders`.

---

## 2. Schemas — `app/schemas/inventory.py`

- `SupplierCreate` / `SupplierUpdate` / `SupplierResponse` (includes `reliability_score`, read-only).
- `PartsInventoryCreate` / `PartsInventoryUpdate` / `PartsInventoryResponse`.
- `PurchaseOrderLineItem` — `{part_id: UUID, qty: int, unit_price: Decimal}`, validated as a Pydantic model even though stored as JSONB.
- `PurchaseOrderCreate` — `supplier_id, order_date, expected_delivery, line_items: list[PurchaseOrderLineItem]`.
- `PurchaseOrderUpdate` — editable pre-receive fields only (`expected_delivery`, `line_items`, `status` transitions other than `received`).
- `PurchaseOrderResponse` — full row + `line_items` echoed back.
- `PurchaseOrderReceiveResponse` — `PurchaseOrderResponse` + `stock_updates: list[{part_id, new_qty}]`.
- `LowStockResponse` — list of `PartsInventoryResponse` with an added `deficit: int` (`reorder_threshold - qty_on_hand`).

---

## 3. Service layer

### 3.1 `app/services/supplier_service.py`

```python
async def create_supplier(db, org_id, data, created_by) -> Supplier: ...
async def list_suppliers(db, org_id, sort_by_reliability=False) -> list[Supplier]: ...
async def update_supplier(db, org_id, supplier_id, data, updated_by) -> Supplier: ...

async def _recalculate_reliability_score(db, org_id, supplier_id) -> Decimal | None:
    """
    reliability_score = count(purchase_orders where status='received'
                               and actual_delivery <= expected_delivery)
                       / count(purchase_orders where status='received')
    Called only from purchase_order_service.receive_purchase_order, inside the same
    transaction. Never called from a scheduled job.
    """
```

### 3.2 `app/services/inventory_service.py`

```python
async def create_part(db, org_id, data, created_by) -> PartsInventory: ...
async def update_part(db, org_id, part_id, data, updated_by) -> PartsInventory: ...
async def list_parts(db, org_id, category=None, supplier_id=None, compatible_make=None, compatible_model=None) -> list[PartsInventory]: ...
async def list_low_stock(db, org_id) -> list[PartsInventory]:
    """WHERE qty_on_hand < reorder_threshold. A comparison, not a background job."""

async def decrement_stock_for_parts_used(db, org_id, parts_used: list[dict]) -> list[dict]:
    """
    Called from maintenance_service.create_mechanic_report (Plan 03), inside that same
    transaction -- this function does NOT open or commit its own transaction.
    For each {part_id, qty} in parts_used:
      1. Fetch the PartsInventory row (org-scoped, is_deleted=False) with a row lock
         (SELECT ... FOR UPDATE) to avoid a race between concurrent decrements.
      2. qty_on_hand -= qty. Raise a validation error if this would go negative
         (never store negative stock -- surface the impossible state as a 400, not silently).
      3. If qty_on_hand < reorder_threshold: append {part_id, low_stock_alert: True} to result.
    Returns the list of alerts; the caller (MechanicReport creation) includes it in its response.
    """

async def increment_stock_for_line_items(db, org_id, line_items: list[dict]) -> list[dict]:
    """
    Called from purchase_order_service.receive_purchase_order, same transaction.
    For each {part_id, qty, unit_price} in line_items: qty_on_hand += qty.
    Returns [{part_id, new_qty}] for the receive response.
    """
```

### 3.3 `app/services/purchase_order_service.py`

```python
async def create_purchase_order(db, org_id, data: PurchaseOrderCreate, created_by) -> PurchaseOrder: ...
async def update_purchase_order(db, org_id, po_id, data, updated_by) -> PurchaseOrder:
    """Rejects edits if status == 'received' -- a received order is immutable, matching the
    append-only spirit applied elsewhere to finalized records."""
async def list_purchase_orders(db, org_id, status=None, supplier_id=None, date_from=None, date_to=None) -> list[PurchaseOrder]: ...

async def receive_purchase_order(db, org_id, po_id, received_by) -> PurchaseOrderReceiveResponse:
    """
    Single transaction:
      1. Fetch PO (org-scoped). 409 if status is already 'received' or 'cancelled'.
      2. Set actual_delivery = today, status = 'received'.
      3. stock_updates = await increment_stock_for_line_items(db, org_id, po.line_items)
      4. await supplier_service._recalculate_reliability_score(db, org_id, po.supplier_id)
      5. Commit. Roll back all of the above together on any failure.
    """
```

---

## 4. Routes

### `app/api/inventory.py`

| Method | Path | Handler |
|---|---|---|
| POST | `/api/v1/inventory` | `create_part` |
| GET | `/api/v1/inventory` | `list_parts` (filters: `category`, `supplier_id`, `compatible_make`, `compatible_model`) |
| PUT | `/api/v1/inventory/{id}` | `update_part` |
| GET | `/api/v1/inventory/low-stock` | `list_low_stock` |

### `app/api/suppliers.py`

| Method | Path | Handler |
|---|---|---|
| POST | `/api/v1/suppliers` | `create_supplier` |
| GET | `/api/v1/suppliers` | `list_suppliers` (query: `sort=reliability_score`) |
| PUT | `/api/v1/suppliers/{id}` | `update_supplier` |

### `app/api/purchase_orders.py`

| Method | Path | Handler |
|---|---|---|
| POST | `/api/v1/purchase-orders` | `create_purchase_order` |
| GET | `/api/v1/purchase-orders` | `list_purchase_orders` (filters: `status`, `supplier_id`, `date_from`, `date_to`) |
| PUT | `/api/v1/purchase-orders/{id}` | `update_purchase_order` |
| PATCH | `/api/v1/purchase-orders/{id}/receive` | `receive_purchase_order` — **the most important endpoint in this domain**, per `backendPlan.md` |

---

## 5. Tests

- `test_low_stock_flag_on_decrement` — decrement crossing below `reorder_threshold` returns the alert.
- `test_low_stock_flag_absent_when_above_threshold`.
- `test_decrement_never_goes_negative` — attempting to consume more than `qty_on_hand` raises a validation error, stock unchanged.
- `test_concurrent_decrement_row_lock` — two simultaneous decrements on the same part don't lose an update (if feasible to simulate; otherwise document the `SELECT ... FOR UPDATE` requirement and assert it's present in the query).
- `test_receive_increments_all_line_items`.
- `test_receive_sets_actual_delivery_and_status`.
- `test_receive_rejects_already_received_order`.
- `test_reliability_score_on_time` — `actual_delivery <= expected_delivery` counts as on-time, assert exact ratio after 2 receives (1 on-time, 1 late).
- `test_reliability_score_null_until_first_receive`.
- `test_low_stock_endpoint_matches_comparison` — cross-check `/inventory/low-stock` against a manual `WHERE` filter over seeded rows.
- `test_purchase_order_immutable_after_receive` — `PUT` on a received order is rejected.
- `test_transaction_rollback_on_stock_increment_failure` — force the reliability-score step to fail, assert stock was not incremented either.
- `test_org_scoping` across all three routers.

---

## 6. Explicit non-goals

- Demand forecasting ("stock hits zero in 45 days") — `ai_agents` `PartsForecasting` agent, reading consumption velocity from `MechanicReport.parts_used` history via MCP.
- Recommending which supplier to reorder from based on lead time + reliability — AI synthesis, not a backend endpoint.

Do not add a `/inventory/{id}/forecast` route here.
