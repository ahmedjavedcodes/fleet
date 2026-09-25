# Spec: Driver & Vehicle Assignment Agent

*Found on disk without a plan document or a verification pass, same profile as `driver-accountability-agent.md` and `strategic-insights-agent.md` before it. Corrected below (`backend/app/api/assignments.py`, `app/schemas/assignment.py`, `app/services/assignment_service.py`) before implementation. This one's factual gap was the largest of the three: the API shape it describes doesn't exist.*

## Problem Statement

Fleet management needs explicit vehicle↔driver pairing to attribute mileage, fuel, and incidents to the right person. Who: `admin`/`fleet_manager` (assignment lifecycle), `driver` (reads — see FR 6's correction: broader than just "their own active pairing"). If not built: unassigned-asset ambiguity and weak accountability trails.

## Functional Requirements

1. Assignment lifecycle: create ("assign") and terminate ("release") the active vehicle↔driver pairing.
2. Resolve `vehicle_plate` → `vehicle_id` via `get_vehicles_tool` and `driver_name` → `driver_id` via `get_drivers_tool` (both reused from `foundation_tools.py`).
3. Conflict pre-check before creating: halt if the vehicle already has an active assignment (any history entry with `released_at: null`) or the target driver already has one (`current_assignment` non-null on their history response). Before terminating: halt if the vehicle has no active assignment. All three are fail-fast UX layers only — the real backend already enforces all three itself (`409` "Vehicle/Driver already has an active assignment", `404` "No active assignment found"), so a race between this pre-check and the actual call is still possible; the agent reports it rather than retrying, same pattern as the Fleet Registry Agent's duplicate-plate handling.
4. Bridge into `AssignmentCreateInput`/`AssignmentTerminateInput`, matching the real `VehicleAssignRequest`/`VehicleReleaseRequest` schemas exactly — note `vehicle_id` is **not** a body field in either; it's the path parameter (see FR 5).
5. **There is no `/api/v1/assignments` resource.** The real endpoints, and the ones `ai_agents/mcp_server/assignment_tools.py` actually wraps:
   - `create_assignment_tool` → `POST /api/v1/vehicles/{vehicle_id}/assign` (not `POST /api/v1/assignments`)
   - `terminate_assignment_tool` → `POST /api/v1/vehicles/{vehicle_id}/release` (not `PUT /api/v1/assignments/{id}/terminate` — no assignment `id` is ever needed by the caller; at most one assignment is active per vehicle at a time, so release is keyed by `vehicle_id`, and the backend finds the active one itself)
   - `get_driver_assignment_history_tool` → `GET /api/v1/drivers/{driver_id}/assignments` (not a generic `GET /api/v1/assignments`)
   - `get_vehicle_assignment_history_tool` → `GET /api/v1/vehicles/{vehicle_id}/assignments`, with an optional `target_date` for a point-in-time query

   There is no flat list-everything endpoint at all — every read is scoped to one driver or one vehicle.
6. RBAC: `create_assignment_tool`/`terminate_assignment_tool` are **admin, fleet_manager** only (the draft's claim here was correct). Reads (`get_driver_assignment_history_tool`, `get_vehicle_assignment_history_tool`) permit **admin, fleet_manager, driver** — broader than the draft's "drivers query their own active pairing" framing: a driver reading their *own* assignment history is row-restricted server-side (`403` on someone else's `driver_id`), but reading a *vehicle's* history has no such restriction for any of the three roles — any driver can see who else has driven a given vehicle. `mechanic` is excluded from every one of the four tools (absent from all three real role tuples).
7. Query support for both driver and vehicle assignment history, per FR 6's roles.

## Behaviour

- **assign_asset:** `inject_context → classify_intent (also gates driver/mechanic out here, before any backend call — see Constraints) → resolve vehicle_id and driver_id → validate no active conflict → create_assignment_tool → reply with the new pairing`.
- **terminate_assignment:** `inject_context → classify_intent → resolve vehicle_id → validate an active assignment exists → terminate_assignment_tool → reply with the release`.
- **query:** `inject_context → classify_intent → call the matching history tool → return results`.
- States: Intent = `assign_asset | terminate_assignment | query`, decided from which of `assign_request`/`terminate_request` the caller populated (no document/image involved, same structural-router approach as the Strategic Insights Agent). Sub-flow = `ResolvingEntities → ValidatingConflicts → Executing → Done | Halted(reason)`.

## Constraints

- Reuses `ai_agents/tools/{api_client,auth_context,sanitize}.py`, `mcp_server/foundation_tools.py`'s vehicle/driver lookups.
- Real endpoint paths per FR 6 — no `/api/v1/assignments` prefix exists anywhere.
- **The RBAC gate for `assign_asset`/`terminate_assignment` runs in `classify_intent`, before entity resolution** — not in `validating_conflicts` as a first draft of this implementation had it. `get_vehicles_tool`/`get_drivers_tool` are ungated reads; deferring the role check to the (gated) history lookup in `validating_conflicts` would let a driver/mechanic's write attempt cost two backend round-trips before being blocked, violating "refuses before making any backend call" (AC 4).

## Edge Cases and Error Handling

| Trigger | Expected Response |
|---|---|
| Assigning a vehicle or driver that already has an active assignment | Halt before `create_assignment_tool`; report the conflict. |
| Backend still returns `409` despite a clean pre-check (race) | Report the conflict; do not retry. |
| Terminating a vehicle with no active assignment | Halt before `terminate_assignment_tool`. |
| Unresolved vehicle plate or driver name | Halt; ask for the correct identifier. |
| `driver` or `mechanic` attempts to create or terminate an assignment | Refused in `classify_intent`, before any backend call. |
| `mechanic` attempts any read tool | Refused before any backend call. |

## Acceptance Criteria

1. **Given** a resolvable vehicle plate and driver name with no conflict, **when** `assign_asset` runs, **then** both resolve and `create_assignment_tool` establishes the pairing.
2. **Given** an active assignment, **when** `terminate_assignment` runs, **then** it's closed via `terminate_assignment_tool`.
3. **Given** a vehicle that's already checked out, **when** conflict validation runs, **then** execution halts with a conflict message before any create call; **given** the backend still `409`s despite a clean pre-check, **then** the agent reports it without retrying.
4. **Given** a `driver` or `mechanic` caller, **when** `assign_asset` or `terminate_assignment` is attempted, **then** the agent refuses before any backend call (including the vehicle/driver lookup reads).
5. **Given** admin/fleet_manager credentials, **when** querying driver or vehicle assignment history, **then** correct records return.
6. **Given** terminating a vehicle with no active assignment, **when** the pre-check runs, **then** execution halts before `terminate_assignment_tool`.
7. **Given** the MCP tools and conflict-checker functions, **when** the test suite runs, **then** all are covered by `pytest` using an injected-dependency fake backend (same pattern as the other five agents) — no live infrastructure required.
