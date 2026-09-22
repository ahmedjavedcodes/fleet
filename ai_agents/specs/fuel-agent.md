# Spec: Fuel Vision & Leakage Auditor Agent

*Source plan: [`ai_agents/Plans/Fuel_Agent.md`](../Plans/Fuel_Agent.md). Corrections below are against the real backend (`backend/app/api/fuel.py`, `trips.py`, `dashboard.py`, `backend/app/schemas/fuel.py`, `accountability.py`) — the plan's endpoint paths, write-role list, and receipt schema don't match what's actually deployed.*

## Problem Statement

Fuel is the fleet's largest variable cost and is entered from paper receipts by hand today, with two consequences: there's no cross-check against the vehicle's own advancing odometer (the backend itself doesn't reject a lower `odometer_reading` — `fuel_service.create_fuel_log` just skips updating `Vehicle.current_odometer` while still creating the log), and the anomaly flag the backend already computes (`FuelLog.is_anomalous`, `cost_per_km`) only surfaces later in a report, not at entry time when it's actionable. Who: admin/fleet_manager/driver (mechanic has no fuel/trip access at all in the real backend). If not built: continued manual re-keying, silent odometer rollbacks, and anomalies discovered after the fact instead of at submission.

## Functional Requirements

1. Extract receipt fields from a photographed fuel receipt (`extract_fuel_receipt`): `station_name`, `receipt_date`, `liters`, `total_cost`, `odometer`, `plate_number` — JPEG/PNG only, same constraint as the Fleet Registry Agent's vision skills.
2. Resolve `plate_number` to a `vehicle_id` via `get_vehicles_tool` — the backend's `FuelLogCreate` requires a UUID `vehicle_id`, not a plate string; this lookup isn't in the plan's flow diagram but is required.
3. Bridge extraction to the backend's real field names: `liters`→`liters_filled`, `odometer`→`odometer_reading`, `receipt_date`→`date`; derive `price_per_liter = total_cost / liters_filled` (required by `FuelLogCreate`, absent from the plan's extraction schema and rarely printed as its own line on a receipt).
4. Validate odometer continuity: halt before `create_fuel_log_tool` if `odometer_reading` is not strictly greater than the vehicle's `current_odometer` (from `get_vehicles_tool`). This is an agent-layer-only guardrail — the real backend has no equivalent rejection.
5. Create the fuel log via `create_fuel_log_tool` once bridging and continuity pass; surface the backend's own `is_anomalous`/`cost_per_km` in the reply rather than recomputing efficiency client-side, so the two can never disagree.
6. Create a trip log (`create_trip_log_tool`) from caller-supplied structured fields (`driver_id`, `vehicle_id`, `start_time`, `end_time`, `start_odometer`, `end_odometer`) relayed in conversation. No vision extraction is defined for trips in the plan, so this spec treats trip logging as structured input only, not a photographed-document flow.
7. When the caller's role is `driver`, force `driver_id` to their own profile before calling `create_trip_log_tool`, regardless of what's supplied. The real `/api/v1/trips` `POST` route does this for fuel logs but **not** for trips (`trip_service.create_trip` takes the request's `driver_id` as-is) — a driver could otherwise log a trip under someone else's name.
8. Query fuel history, trip history, and fuel trends (`get_fuel_logs_tool`, `get_trip_logs_tool`, `get_fuel_trends_tool`).
9. RBAC: gate `create_fuel_log_tool` / `create_trip_log_tool` to **admin, driver only** — the plan lists `fleet_manager` as a write role, but the real backend's `_WRITE_ROLES` for both `/api/v1/fuel` and `/api/v1/trips` is `(admin, driver)`; fleet_manager is read-only on both. Gate `get_fuel_trends_tool` to admin/fleet_manager (plan is correct here).

**Out of scope:** editing existing fuel/trip logs, attaching a receipt image after the fact (`POST /fuel/{id}/receipt`), mechanic access (none exists), CSV bulk trip-sheet ingestion (`tools/file_parsers.py`'s existing `parse_trip_sheet_csv` is a separate, non-agentic path).

## Behaviour

- **receipt_onboard:** `inject_context → classify_intent → extract_fuel_receipt → resolve plate_number→vehicle_id → bridge/sanitize (derive price_per_liter) → validate_odometer_continuity → create_fuel_log_tool → reply with created log, flagging is_anomalous if true`.
- **trip_log:** `inject_context → classify_intent → collect structured trip fields → (force driver_id if role=driver) → create_trip_log_tool`.
- **query:** `inject_context → classify_intent → call the matching get_*_tool → return results`.
- States: Intent = `receipt_onboard | trip_log | query`. Onboarding sub-flow = `Extracting → ResolvingVehicle → Sanitizing → ValidatingOdometer → Creating → Done | Halted(reason)`.

## Constraints

- Reuses `ai_agents/tools/{api_client,auth_context,sanitize}.py` and `core/llm_config.py`'s `GROQ` provider unchanged — no new infrastructure.
- Real endpoint paths: `/api/v1/fuel` (not `/fuel-logs`), `/api/v1/trips` (not `/trip-logs`), `/api/v1/dashboard/fuel-trends` (plan correct here).
- Images: JPEG/PNG only, one receipt per onboarding turn.
- The odometer-continuity guardrail only protects traffic through this agent — a caller hitting `/api/v1/fuel` directly still bypasses it, since the backend doesn't enforce it. Fixing that is a backend change, out of scope here.

## Edge Cases and Error Handling

| Trigger | Expected Response |
|---|---|
| Receipt `odometer_reading` ≤ vehicle's current `current_odometer` | Halt before `create_fuel_log_tool`; report the continuity violation. |
| Extracted `plate_number` matches no vehicle in `get_vehicles_tool` | Halt; ask for a clearer photo or the correct plate. |
| Receipt image unreadable (blurry, wrong document, unsupported language) | Halt; ask for a clearer photo — no fuel log created. |
| Non-JPEG/PNG upload | Reject before invoking the vision skill. |
| `fleet_manager` attempts `create_fuel_log_tool` / `create_trip_log_tool` | Agent refuses before any backend call. |
| `driver` submits a trip log with someone else's `driver_id` | Agent overwrites it with the caller's own profile id before calling `create_trip_log_tool`. |

## Acceptance Criteria

1. **Given** a clear fuel receipt photo, **when** `receipt_onboard` runs, **then** the plate resolves to a `vehicle_id`, fields bridge correctly (including a derived `price_per_liter`), and `create_fuel_log_tool` succeeds when the odometer is continuous.
2. **Given** a receipt whose `odometer_reading` is not strictly greater than the vehicle's `current_odometer`, **when** `validate_odometer_continuity` runs, **then** the workflow halts before any create call.
3. **Given** a `plate_number` that matches no vehicle on file, **when** vehicle resolution runs, **then** the workflow halts and asks for a clearer photo or the correct plate.
4. **Given** an unreadable receipt photo, **when** extraction runs, **then** the workflow halts and asks for a clearer photo — no fuel log is created.
5. **Given** a created fuel log whose backend response has `is_anomalous: true`, **when** the agent replies, **then** that flag and `cost_per_km` are surfaced, never recomputed client-side.
6. **Given** a `fleet_manager` caller, **when** they attempt `create_fuel_log_tool` or `create_trip_log_tool`, **then** the agent refuses before any backend call.
7. **Given** a `driver` caller submitting a trip log for a different `driver_id`, **when** `create_trip_log_tool` runs, **then** the agent overrides it to the caller's own profile id first.
8. **Given** any of admin/fleet_manager/driver, **when** they query fuel or trip history, **then** `get_fuel_logs_tool`/`get_trip_logs_tool` returns results row-filtered to the caller (drivers see only their own).
9. **Given** admin/fleet_manager, **when** they call `get_fuel_trends_tool`, **then** results return; **given** driver/mechanic, **then** the agent refuses.
10. **Given** the MCP tools and `extract_fuel_receipt`, **when** the test suite runs, **then** all are covered by `pytest` using mocked backend/vision responses via injected dependencies (same pattern as `FoundationAgentDeps`) — no live backend or LLM call required.
