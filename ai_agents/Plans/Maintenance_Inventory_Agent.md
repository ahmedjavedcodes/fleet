# Spec — Maintenance & Parts Inventory Agent (`Maintenance Agent`)

## 1. Problem Statement

Fleet maintenance spans two critical operational bottlenecks:

- Mechanics spending time translating unstructured work orders or repair notes into structured service logs.
- Unexpected stockouts of high-turnover spare parts (filters, brake pads, fluids) grounding vehicles prematurely.

**Who:** `admin`, `fleet_manager`, `mechanic` (writes/management), and `driver` (read-only history).

**If not built:** Continued manual entry overhead, unverified parts usage leading to inventory discrepancies, and delayed service logging.

---

## 2. Functional Requirements

1. **Work Order Parsing** (`parse_work_order_text` or vision)
   Extract structured repair data from raw mechanic notes, work orders, or diagnostic receipts: `issue_description`, `parts_used` (SKU/name + quantity), `labor_hours`, `cost`, and `vehicle_plate`.

2. **Parts Invoice Ingestion** (`parse_parts_invoice`)
   Parse supplier delivery slips or parts invoices (JPEG/PNG or structured text) to extract spare part receipts, quantities, unit costs, and SKUs.

3. **Vehicle & Part Resolution**
   Resolve extracted `plate_number` to a `vehicle_id` UUID, and match item descriptions/SKUs against the parts inventory database (`get_inventory_tool`).

4. **Inventory Stock Check Sub-Agent**
   Before finalizing a maintenance log that consumes parts, verify that sufficient stock exists (`stock_quantity >= required_quantity`). If inventory dips below safety thresholds, flag a restock warning.

5. **Bridge & Sanitize**
   Map extracted fields to backend-ready schema inputs (`MaintenanceLogCreateInput`, `InventoryUpdateInput`).

6. **MCP Tool Wrappers** (`ai_agents/mcp_server/maintenance_tools.py`)
   - `get_maintenance_logs_tool` — `GET /api/v1/maintenance`
   - `create_maintenance_log_tool` — `POST /api/v1/maintenance`
   - `get_inventory_tool` — `GET /api/v1/inventory`
   - `update_inventory_tool` — `PUT /api/v1/inventory` (or stock adjustment endpoints)

7. **RBAC Enforcement**
   Gate maintenance creation and inventory updates to authorized roles (`admin`, `fleet_manager`, `mechanic`). Restrict driver access strictly to viewing service records.

8. **Query Support**
   Allow querying maintenance service history, repair costs, and current spare parts stock levels.

---

## 3. Behavior

**`maintenance_onboard`**
`inject_context` → `classify_intent` → `extract_work_order` → `resolve vehicle_id` → `check inventory stock levels` → `bridge & sanitize` → `create_maintenance_log_tool` → reply with service summary and inventory updates.

**`inventory_restock`**
`inject_context` → `classify_intent` → `parse parts invoice` → `update_inventory_tool` → return restock confirmation.

**`query`**
`inject_context` → `classify_intent` → call matching `get_*_tool` → return results.

### States

- **Intent:** `maintenance_onboard` | `inventory_restock` | `query`
- **Sub-flow:** `Extracting` → `ResolvingAssets` → `CheckingInventory` → `Sanitizing` → `Creating` → `Done` | `Halted(reason)`

---

## 4. Constraints

- Reuses existing modules (`tools/api_client.py`, `tools/auth_context.py`, `tools/sanitize.py`, `core/llm_config.py`).
- Endpoint paths aligned with backend REST design (`/api/v1/maintenance`, `/api/v1/inventory`).
- Images/Documents: JPEG/PNG for visual invoices/work orders, plus raw text parsing for mechanic notes.

---

## 5. Edge Cases and Error Handling

| Trigger | Expected Response |
| --- | --- |
| Work order specifies a part whose quantity exceeds available stock | Halt before `create_maintenance_log_tool`; flag insufficient inventory. |
| Extracted `plate_number` matches no vehicle in inventory | Halt; request correct vehicle plate or ID. |
| Unreadable work order note or blurry invoice photo | Halt; ask for clearer input. |
| Unauthorized role (`driver`) attempts to log maintenance or update inventory | Agent refuses before making any backend call. |

---

## 6. Acceptance Criteria

1. Given a clear work order or mechanic note, when `maintenance_onboard` runs, then the vehicle plate resolves, required parts are checked against stock, and `create_maintenance_log_tool` succeeds.
2. Given a repair log requesting parts exceeding current inventory, when the inventory check sub-agent runs, then execution halts with a stock deficit warning.
3. Given an invoice for spare parts restock, when processed, then inventory levels update correctly via the inventory tool.
4. Given a driver user attempting to log maintenance or modify inventory, when the request hits the MCP wrapper, then the agent refuses due to RBAC restrictions.
5. Given valid admin/mechanic credentials, when querying maintenance logs or inventory, then correct records are returned.
