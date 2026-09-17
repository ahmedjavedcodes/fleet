# Spec 02 — Unpredictable Spare Parts

**Derived from:** [`backendPlan.md`](../backendPlan.md#problem-2--unpredictable-spare-parts) · [`plans/02-unpredictable-spare-parts.md`](../plans/02-unpredictable-spare-parts.md)
**Status:** Ready for execution
**Depends on:** [`specs/00-foundation.md`](./00-foundation.md), `AuditMixin`/`OrgScopedMixin`, `require_role`. **Shares a transaction boundary with Spec 03** (`MechanicReport` creation triggers stock decrement) — see Constraints §4.7.

---

## 1. Problem Statement

A truck breaks down; the mechanic needs a part; the shelf is empty; the supplier quotes a 2–3 week import lead time. Nobody tracked that the last unit of that part was consumed two months ago. A faster supplier might exist, but nobody tracks which suppliers actually deliver on time versus which ones don't. The fleet has zero visibility into current stock levels, consumption velocity, or supplier reliability — so every shortage feels like a surprise even though the data to predict it (past consumption, past deliveries) already exists in the business.

---

## 2. Functional Requirements

| ID | Requirement |
|---|---|
| FR-2.1 | The system shall allow registering a supplier: name, contact email, phone, average lead time (informational). |
| FR-2.2 | The system shall allow registering a part in inventory: part number, name, category, compatible vehicle makes/models, current quantity, reorder threshold, unit cost, default supplier. |
| FR-2.3 | The system shall allow listing parts filterable by category, supplier, and compatible vehicle make/model. |
| FR-2.4 | The system shall expose a "low stock" list of every part where `qty_on_hand < reorder_threshold`. |
| FR-2.5 | When a mechanic report records parts consumed (`parts_used: [{part_id, qty}]`), the system shall decrement `qty_on_hand` for each part and report which ones dropped below their reorder threshold as a result. |
| FR-2.6 | The system shall allow creating a purchase order with a supplier, expected delivery date, and line items (`part_id, qty, unit_price`). |
| FR-2.7 | The system shall allow marking a purchase order as received, which increments stock for every line item and recalculates the supplier's reliability score. |
| FR-2.8 | The system shall compute `Supplier.reliability_score` as the ratio of on-time received orders (`actual_delivery <= expected_delivery`) to all received orders for that supplier. |
| FR-2.9 | The system shall allow listing suppliers sorted by reliability score. |
| FR-2.10 | The system shall reject edits to a purchase order once it has been marked `received`. |
| FR-2.11 | The system shall never forecast demand, recommend reorder timing, or choose a supplier automatically — these are out of scope for this module. |

---

## 3. Behaviour

### 3.1 Stock decrement (triggered from Spec 03's `POST /maintenance/{id}/mechanic-report`)

1. For each `{part_id, qty}` in `parts_used`: load the `PartsInventory` row (organization-scoped) with a row lock (`SELECT ... FOR UPDATE`) to prevent a lost update under concurrent consumption.
2. `qty_on_hand -= qty`. If this would go negative, reject the entire mechanic-report creation with a validation error — stock is never stored negative.
3. If the resulting `qty_on_hand < reorder_threshold`, include `{part_id, low_stock_alert: true}` in the result returned to the caller.
4. This function does not open or commit its own transaction — it runs inside the caller's (Spec 03's) transaction and rolls back with it.

### 3.2 Stock increment + supplier scoring (`PATCH /purchase-orders/{id}/receive`)

1. Load the purchase order (organization-scoped). If `status` is already `received` or `cancelled`, reject with `409`.
2. Set `actual_delivery = today`, `status = received`.
3. For each line item, increment the corresponding `PartsInventory.qty_on_hand`.
4. Recalculate `Supplier.reliability_score = count(received orders where actual_delivery <= expected_delivery) / count(received orders)` for that supplier, across all its purchase orders.
5. Commit steps 2–4 as one transaction. Roll back all of it if any step fails.
6. Return the updated order plus the per-part new quantities.

### 3.3 Low-stock list (`GET /inventory/low-stock`)

- A plain comparison query (`qty_on_hand < reorder_threshold`), evaluated fresh on every call. No stored "is_low_stock" flag, no background job.

---

## 4. Constraints

1. **Organization scoping** on every table and query, as elsewhere in this backend.
2. **All side effects happen inside the transaction of the triggering write** — mechanic-report creation and stock decrement are one transaction; purchase-order receive, stock increment, and reliability scoring are one transaction. No message queue, no eventual consistency.
3. **Threshold alerting is a return value, not a notification system.** The frontend reads the flag from the API response; no polling, no background scan.
4. **Stock never goes negative.** This is enforced at write time as a hard validation rule, not corrected after the fact.
5. **`reliability_score` is null until a supplier's first received order**, and is recalculated (not incrementally patched) on every subsequent receive — always derived fresh from the full order history at that moment.
6. **`PurchaseOrder.line_items` and `PartsInventory.compatible_vehicles` are JSONB**, not normalized join tables — a deliberate tradeoff at this scale. Do not introduce join tables without revisiting this decision.
7. **A received purchase order is immutable** except through the receive action itself; `PUT` on a received order is rejected.
8. **Concurrent stock mutations are serialized** via row-level locking on `PartsInventory`, not application-level mutexes.
9. **Access control per the Spec 00 permission matrix:** `PartsInventory`/`PurchaseOrder` are `admin: full`, `fleet_manager: full`, `driver: none`, `mechanic: read-only`. `Supplier` is `admin: full`, `fleet_manager: full`, `driver: read-only`, `mechanic: read-only`.
10. **No row-level ("own only") filtering in this domain.** Unlike `FuelLog`/`TripLog`, parts/suppliers/orders aren't owned by an individual — access is gated by role alone, applied on top of the standard organization scope.

---

## 5. Edge Cases and Error Handling

| # | Scenario | Expected behavior |
|---|---|---|
| EC-1 | `parts_used` references a `part_id` that doesn't exist or belongs to another organization | `404`/validation error; the entire mechanic-report creation (and any partial decrements already applied in-transaction) is rolled back. |
| EC-2 | Consuming more of a part than `qty_on_hand` | `400`; stock unchanged; no mechanic report is created (all-or-nothing). |
| EC-3 | Two mechanic reports decrementing the same part submitted concurrently | Row locking ensures both decrements apply correctly in sequence; neither is lost. |
| EC-4 | Receiving a purchase order that's already `received` | `409`; no stock change, no score recalculation. |
| EC-5 | Receiving a purchase order that's `cancelled` | `409`; same as above. |
| EC-6 | `PUT` on a `received` purchase order | Rejected (`409` or `422`); no field changes persisted. |
| EC-7 | A supplier with zero received orders | `reliability_score` is `null`, not `0` and not omitted — distinguishes "unknown" from "known bad." |
| EC-8 | `actual_delivery == expected_delivery` exactly | Counts as on-time (`<=`, not `<`). |
| EC-9 | A part with `reorder_threshold = 0` | Never appears in low-stock unless `qty_on_hand` goes negative, which is itself prevented (EC-2) — so effectively never flags; this is expected, not a bug. |
| EC-10 | Registering a part with no `supplier_id` | Allowed — `supplier_id` is optional (a part may have multiple potential suppliers, tracked per purchase order instead). |
| EC-11 | Cross-organization access to inventory, suppliers, or purchase orders | Never visible, in list or detail views. |
| EC-12 | `driver` calls any inventory or purchase-order route | `403` — matrix grants `driver` no access to these domains at all. |
| EC-13 | `mechanic` attempts `POST /inventory` or `PATCH /purchase-orders/{id}/receive` | `403` — mechanic is read-only on both. |
| EC-14 | `mechanic` calls `GET /inventory`, `/inventory/low-stock`, or `GET /purchase-orders` | `200` — explicitly allowed (read-only). |

---

## 6. Acceptance Criteria

- [ ] **AC-1:** Submitting a mechanic report that consumes a part crossing below its `reorder_threshold` returns a `low_stock_alert` for that part.
- [ ] **AC-2:** Submitting a mechanic report that consumes a part but leaves it above threshold returns no alert for that part.
- [ ] **AC-3:** Attempting to consume more units than `qty_on_hand` fails with a `400` and leaves `qty_on_hand` unchanged.
- [ ] **AC-4:** `GET /inventory/low-stock` returns exactly the set of parts where `qty_on_hand < reorder_threshold`, matching a manual query over the same seed data.
- [ ] **AC-5:** `PATCH /purchase-orders/{id}/receive` increments `qty_on_hand` for every line item by the ordered quantity.
- [ ] **AC-6:** After receiving an order, `actual_delivery` is set to the receive date and `status` becomes `received`.
- [ ] **AC-7:** Receiving a second order for a supplier, one on-time and one late, yields `reliability_score = 0.5`.
- [ ] **AC-8:** A supplier with no received orders has `reliability_score: null` in `GET /suppliers`.
- [ ] **AC-9:** Receiving an already-`received` order returns `409` and does not change stock or the reliability score a second time.
- [ ] **AC-10:** `PUT /purchase-orders/{id}` on a received order is rejected.
- [ ] **AC-11:** Forcing the supplier-score recalculation step to fail during a receive leaves stock levels unchanged (full transaction rollback).
- [ ] **AC-12:** `GET /suppliers?sort=reliability_score` returns suppliers ordered correctly, nulls handled consistently (e.g. sorted last).
- [ ] **AC-13:** No cross-organization data appears in inventory, supplier, or purchase-order responses.
- [ ] **AC-14:** `driver` tokens receive `403` on every route in this domain (inventory, suppliers, purchase orders alike — except supplier `GET`, which is read-only-allowed for all roles).
- [ ] **AC-15:** `mechanic` tokens succeed on all `GET` routes in this domain and receive `403` on every write route (`POST`/`PUT`/`PATCH`).
