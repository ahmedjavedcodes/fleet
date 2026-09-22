# Spec: Maintenance & Parts Inventory Agent

*Source plan: [`ai_agents/Plans/Maintenance_Inventory_Agent.md`](../Plans/Maintenance_Inventory_Agent.md). Verified against the real backend (`backend/app/api/maintenance.py`, `inventory.py`, `app/schemas/maintenance.py`, `inventory.py`, `app/services/maintenance_service.py`, `inventory_service.py`) — the plan gets the RBAC split and the write flow structurally wrong in ways worth correcting up front, not just the field names.*

## Problem Statement

Mechanics translate paper work orders into service logs by hand, and high-turnover parts (filters, brake pads, fluids) run out unexpectedly because nothing checks stock before a repair consumes it. Who: `admin` and `mechanic` create maintenance logs; `admin` and `fleet_manager` manage inventory — these are two **different** role pairs, not one shared "admin/fleet_manager/mechanic" group as the plan assumes (see Functional Requirements). `driver` has **no** access to either resource in the real backend — the plan's claim that drivers get read-only maintenance history is incorrect for the system as it exists today; that would be a backend RBAC change, out of scope here. If not built: continued manual log entry and stockouts discovered only after a vehicle is already grounded.

## Functional Requirements

1. Extract structured data from a work order / mechanic note (`extract_work_order`): `issue_description`, `service_type` (must map to the backend's `ServiceType` enum: `oil_change`, `brake_service`, `tire_rotation`, `engine_repair`, `transmission`, `electrical`, `body_work`, `general_inspection`, `other`), `parts_used` (name/SKU + qty pairs), `cost`, `vehicle_plate`, `odometer`. **`labor_hours` has no backend field to land in** — the plan lists it as an extraction target, but `MaintenanceLogCreate` has none; fold it into free-text `description` instead of inventing a field.
2. Extract structured data from a parts invoice / delivery slip (`extract_parts_invoice`): line items of `part_number`/`name`, `qty_received`, `unit_cost`.
3. Resolve `vehicle_plate` → `vehicle_id` via `get_vehicles_tool` (same pattern as the Fuel Agent). Resolve each work-order line item's name/SKU and each invoice line item to an existing `part_id` via `get_inventory_tool` (match on `part_number`, falling back to `name`).
4. **Maintenance logging is a two-step backend flow, not one call** — the plan's single `create_maintenance_log_tool` step is wrong: `MaintenanceLogCreate` (`POST /api/v1/maintenance`) carries no `parts_used` field at all. Parts consumption happens through a *separate*, required second call, `MechanicReportCreate` (`POST /api/v1/maintenance/{log_id}/mechanic-report`), which is also where the backend decrements stock and returns `low_stock_alerts`. The agent must call both in sequence: create the log, then attach the report.
5. Before calling `create_mechanic_report_tool`, pre-check each resolved part's `qty_on_hand` (via `get_inventory_tool`) against the requested `qty`; halt with a stock-deficit message if any line item would go negative. This is a fail-fast UX layer only — the backend's `decrement_stock_for_parts_used` is the real authority: it row-locks each part (`SELECT ... FOR UPDATE`) and returns `400 Insufficient stock` if a decrement would go negative, so a race between this pre-check and the report call is still possible and must be handled (see Edge Cases).
6. Restock inventory from a parsed invoice via `update_inventory_tool` (`PUT /api/v1/inventory/{part_id}`), setting `qty_on_hand` to `current + qty_received` per resolved part. **Known limitation, not solved here:** this field is an absolute replacement, not a delta, and the endpoint has no row-locking — two concurrent restocks racing on the same part can silently drop one increment. The backend's `PurchaseOrder` → `/receive` flow (`purchase_order_service.receive_purchase_order`) already solves this properly with locking and reliability-score side effects, but matching an invoice to an existing PO is a larger feature the plan doesn't ask for; out of scope here.
7. MCP tools (`ai_agents/mcp_server/maintenance_tools.py`): `get_maintenance_logs_tool` (`GET /api/v1/maintenance`), `create_maintenance_log_tool` (`POST /api/v1/maintenance`), `create_mechanic_report_tool` (`POST /api/v1/maintenance/{log_id}/mechanic-report`), `get_inventory_tool` (`GET /api/v1/inventory`), `get_low_stock_tool` (`GET /api/v1/inventory/low-stock`), `update_inventory_tool` (`PUT /api/v1/inventory/{part_id}`).
8. RBAC, corrected against the real routers:
   - `create_maintenance_log_tool` / `create_mechanic_report_tool`: **admin, mechanic** (not `fleet_manager` — the real `_FULL_WRITE_ROLES` on `/api/v1/maintenance` is `(admin, mechanic)`; fleet_manager is read-only there).
   - `update_inventory_tool`: **admin, fleet_manager** (not `mechanic` — the real `_WRITE_ROLES` on `/api/v1/inventory` is `(admin, fleet_manager)`; mechanic is read-only there).
   - Reads (`get_maintenance_logs_tool`, `get_inventory_tool`, `get_low_stock_tool`): **admin, fleet_manager, mechanic**. `driver` is excluded from all six tools — the real backend grants it no maintenance or inventory access at all.
9. Query support for maintenance history and current stock levels, per FR7's read roles.

## Behaviour

- **maintenance_onboard:** `inject_context → classify_intent → extract_work_order → resolve vehicle_id → create_maintenance_log_tool → resolve parts line items → check stock → create_mechanic_report_tool → reply with the log, the report, and any low_stock_alerts`.
- **inventory_restock:** `inject_context → classify_intent → extract_parts_invoice → resolve part line items → update_inventory_tool per line → reply with new stock levels`.
- **query:** `inject_context → classify_intent → call the matching get_*_tool → return results`.
- States: Intent = `maintenance_onboard | inventory_restock | query`. `maintenance_onboard` sub-flow = `Extracting → ResolvingAssets → CreatingLog → CheckingInventory → CreatingReport → Done | Halted(reason)`.

## Constraints

- Reuses `ai_agents/tools/{api_client,auth_context,sanitize}.py` and `core/llm_config.py`'s `GROQ` provider unchanged.
- Real endpoint paths: `/api/v1/maintenance`, `/api/v1/maintenance/{log_id}/mechanic-report`, `/api/v1/inventory`, `/api/v1/inventory/{part_id}`, `/api/v1/inventory/low-stock` (plan's paths were directionally right for the first two, silent on the rest).
- Images/documents: JPEG/PNG for photographed work orders/invoices; raw text also accepted for typed mechanic notes (no vision call needed for plain text).
- If `create_mechanic_report_tool` fails after `create_maintenance_log_tool` already succeeded, the `MaintenanceLog` row is **not** rolled back (they're separate backend transactions) — the agent must report a partially-completed onboarding (log created, parts not recorded) rather than claim total failure.

## Edge Cases and Error Handling

| Trigger | Expected Response |
|---|---|
| A work-order part's requested `qty` exceeds `qty_on_hand` (pre-check) | Halt before `create_mechanic_report_tool`; report the stock deficit. |
| Backend still returns `400 Insufficient stock` despite a clean pre-check (race) | Report the conflict; do not retry the report call. The `MaintenanceLog` itself still exists — say so. |
| `vehicle_plate` matches no vehicle | Halt before creating anything; ask for the correct plate. |
| A part name/SKU matches no inventory record | Halt before `create_mechanic_report_tool`; ask for the correct part. |
| Unreadable work order note or blurry invoice photo | Halt; ask for clearer input. |
| `driver` attempts any of the six tools | Agent refuses before any backend call. |
| `fleet_manager` attempts `create_maintenance_log_tool`/`create_mechanic_report_tool` | Agent refuses (real backend excludes fleet_manager from maintenance writes). |
| `mechanic` attempts `update_inventory_tool` | Agent refuses (real backend excludes mechanic from inventory writes). |

## Acceptance Criteria

1. **Given** a clear work order naming a real vehicle and parts within stock, **when** `maintenance_onboard` runs, **then** the plate and parts resolve, `create_maintenance_log_tool` succeeds, and `create_mechanic_report_tool` succeeds with no low-stock alerts.
2. **Given** a work order requesting a part quantity exceeding `qty_on_hand`, **when** the pre-check runs, **then** execution halts before `create_mechanic_report_tool` with a stock-deficit message.
3. **Given** the backend returns `400 Insufficient stock` despite a clean pre-check, **when** `create_mechanic_report_tool` is called, **then** the agent reports the conflict without retrying, and notes the maintenance log itself was still created.
4. **Given** a parts invoice for an existing part, **when** `inventory_restock` runs, **then** `qty_on_hand` updates to `current + qty_received` via `update_inventory_tool`.
5. **Given** a `driver` caller, **when** any maintenance or inventory tool is attempted, **then** the agent refuses before any backend call.
6. **Given** a `fleet_manager` caller, **when** `create_maintenance_log_tool` or `create_mechanic_report_tool` is attempted, **then** the agent refuses; **given** the same caller queries maintenance logs or inventory, **then** it succeeds.
7. **Given** a `mechanic` caller, **when** `update_inventory_tool` is attempted, **then** the agent refuses; **given** the same caller creates a maintenance log/report or queries inventory, **then** it succeeds.
8. **Given** admin/fleet_manager/mechanic, **when** querying maintenance history or stock levels, **then** correct records return.
9. **Given** the MCP tools and both extraction skills, **when** the test suite runs, **then** all are covered by `pytest` using mocked backend/vision responses via injected dependencies (same pattern as `FoundationAgentDeps`/`FuelAgentDeps`) — no live backend or LLM call required.
