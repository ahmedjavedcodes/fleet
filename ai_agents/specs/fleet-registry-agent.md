# Spec: Fleet Registry Agent

*Spec 00 (Foundation) agentic module — onboarding and lookup for Vehicles, Drivers, and Suppliers.*
*Source plan: [`ai_agents/Plans/Fleet Regitry Agent.md`](../Plans/Fleet%20Regitry%20Agent.md)*

## Problem Statement

This is a multi-tenant SaaS platform, so the normal onboarding path today is manual:
an administrator or fleet manager reads a paper driver's license, vehicle registration
card/VIN plate, or supplier invoice/registration document, and re-types the relevant
fields into the platform's existing create forms (`POST /api/v1/vehicles`,
`/api/v1/drivers`, `/api/v1/suppliers`).

That re-keying step is slow, error-prone, and unscoped for growth:

- Typos in `plate_number`, `vin`, or `license_number` silently corrupt records that
  later specs depend on for correctness — compliance scheduling
  (`/api/v1/compliance/matrix`) keys off odometer/vehicle identity, custody tracking
  keys off vehicle/driver identity, and fuel-efficiency anomaly detection keys off
  accurate vehicle records.
- Nothing today proactively checks a driver's license expiration date at onboarding
  time — an expired license can be entered and the organization has no signal until
  something downstream (an incident, an audit) surfaces it.
- Nothing today proactively checks for duplicate plates/license numbers before
  submission; a duplicate only surfaces as a raw `409` from the backend, with no
  guided recovery.
- Every organization onboarding photographable documents already has the source data
  in image form — there's no ingestion path that uses that, so the manual transcription
  step is pure overhead.

**Who hits this:** Administrators and Fleet Managers (the only roles with write access
to these entities per the backend's RBAC).

**If this isn't built:** onboarding stays a fully manual, error-prone retyping task with
no systematic expiry enforcement and no duplicate prevention beyond a raw backend
error, and the photographable documents organizations already have go unused.

---

## Functional Requirements

**Read path (all roles)**

1. Accept a natural-language query about existing Vehicles, Drivers, or Suppliers and
   return backend-filtered results via `get_vehicles_tool` / `get_drivers_tool` /
   `get_suppliers_tool`.

**Write path — vision extraction (admin, fleet_manager only)**

2. Extract structured data from a photographed driver's license
   (`extract_license_data`): `first_name`, `last_name`, `license_number`,
   `phone_number`, `expiration_date`.
3. Extract structured data from a photographed vehicle registration card or VIN plate
   (`extract_vehicle_doc`): `plate_number`, `make`, `model`, `year`, `vin`,
   `initial_odometer`.
4. Extract structured data from a photographed supplier invoice or registration
   document (`extract_supplier_doc`) — **new in this spec, not in the original plan.**
   Output is constrained to fields `SupplierCreate` actually accepts: `name`,
   `contact_email`, `phone`. Any other extractable text (address, tax/registration ID)
   is discarded rather than submitted, since the backend schema has no field for it.

**Write path — validation & submission**

5. Reject a driver license whose `expiration_date` is not strictly after today's date;
   halt before any create call.
6. Before creating, pre-check for an existing match via the read tools: `plate_number`
   for vehicles, `license_number` for drivers, case-insensitive `name` for suppliers
   (the only near-unique field `SupplierCreate` exposes).
7. Sanitize extracted text fields before submission (e.g. normalize plate-number
   spacing/casing: `ABC 123` → `ABC-123`).
8. Bridge extraction output to the backend's actual create schemas — field names differ
   (`first_name`+`last_name` → `full_name`; `phone_number` → `phone`;
   `expiration_date` → `license_expiry`; `initial_odometer` → `current_odometer`) and
   `VehicleCreate` requires `fuel_type`, which no vision skill produces. When a
   required field has no extracted value, ask the requester for it in-chat and wait
   for a reply before calling the create tool.
9. Create the record via `create_vehicle_tool` / `create_driver_tool` /
   `create_supplier_tool` only after extraction, bridging, sanitization, expiry check
   (drivers), and duplicate pre-check have all passed.
10. Enforce RBAC at the agent layer: refuse to invoke any `create_*_tool` when the
    caller's role is `driver` or `mechanic`, without making a backend call. (The
    backend independently returns `403` for the same case — this is a
    fail-fast/UX layer, not the security boundary itself.)
11. Inject the caller's `organization_id` and `role` (from their JWT) into every tool
    call and into the agent's system prompt context.
12. Classify each incoming request as **Onboard** (write) or **Query** (read) via a
    router node before dispatching to any sub-agent or tool.

**Explicitly out of scope for this spec**

- Editing/updating an existing Vehicle, Driver, or Supplier record through the agent —
  corrections go through the existing frontend/backend `PUT` endpoints directly.
- Multi-document or multi-page batch onboarding in a single request — one entity, one
  image, per onboarding turn.
- Any entity type outside Vehicles, Drivers, Suppliers (fuel logs, incidents,
  maintenance records, etc. belong to other agents/specs).
- The login/authentication flow itself — the agent assumes a valid JWT is already
  present in context.

---

## Behaviour

### Onboarding flow (write)

1. User submits a request with one attached image (license, vehicle doc, or supplier
   doc) to the Fleet Registry Agent.
2. **Agent Router & Context Injector** reads the caller's JWT, extracts
   `organization_id` and `role`, and classifies intent as **Onboard**.
3. Router dispatches to the write workflow and selects the matching vision extraction
   skill for the declared/inferred document type.
4. The vision skill returns a structured Pydantic object.
5. Sanitization normalizes extracted text fields.
6. Validation sub-agents run in order:
   - `LicenseInspectorSubAgent` (drivers only) — checks `expiration_date`; halts on
     failure.
   - `PreSearchDuplicateSubAgent` — looks up the entity's near-unique field via the
     matching `get_*_tool`; halts on a match.
7. If a backend-required field has no extracted value (e.g. `fuel_type`), the agent
   asks the user for it and waits for a reply.
8. Agent calls the matching `create_*_tool` — gated on caller role being `admin` or
   `fleet_manager`.
9. On success, the agent echoes the backend's created record back to the user.

### Query flow (read)

1. User submits a natural-language question about existing vehicles/drivers/suppliers,
   no image attached.
2. Router classifies intent as **Query**.
3. Agent calls the matching `get_*_tool` with filters derived from the request.
4. Agent returns/summarizes the backend's response.

### States

- **Intent:** `Onboard` | `Query` — decided once, by the router, per request.
- **Onboarding sub-flow:** `Extracting` → `Sanitizing` → `ValidatingExpiry`
  (drivers only) → `ValidatingDuplicate` → `AwaitingMissingField` (conditional) →
  `Creating` → `Done` | `Halted(reason)`.

### Role-based behaviour difference

`driver` and `mechanic` callers can use the Query flow freely. In the Onboard flow,
their request is refused at step 8 (tool gating) before any backend call is attempted.

---

## Constraints

- All writes and structured reads go through the existing backend REST API — no direct
  database writes, and no reliance on the raw-SQL `query_fleet_data` MCP tool (every
  capability here maps to an existing backend endpoint). Matches root `CLAUDE.md`
  directive #6 (modular separation between `ai_agents/` and `backend/`).
- **LLM providers:** Groq-hosted vision-capable models (`GROQ_API_KEY`) power
  `extract_license_data`, `extract_vehicle_doc`, `extract_supplier_doc`; the hosted
  Llama API (`LLAMA_API_KEY`) powers the router and validation sub-agents' text
  reasoning. Both need new provider branches added to `ai_agents/core/llm_config.py`
  alongside the existing `local_llama` / `claude_anthropic` / `claude_openrouter`
  entries.
- Extraction output must be forced into Pydantic v2 models (LangChain schema binding or
  Instructor) — no free-text parsing downstream (root directive #5).
- **Input images:** JPEG/PNG only, one image per document, one document per onboarding
  request. No PDF, no multi-page, no multi-document batches.
- Orchestration is a LangGraph graph (`FoundationAgentState`), consistent with the rest
  of `ai_agents/agents/`.
- Every tool call must carry the caller's `organization_id`; the backend's
  `OrgScopedMixin` is the actual multi-tenancy enforcement boundary — the agent must
  never attempt a cross-org lookup.
- Sequencing follows the source plan's four phases (HTTP client/tools → RBAC/context →
  vision skills → LangGraph orchestration); no fixed calendar deadline is set beyond
  that order.

---

## Edge Cases and Error Handling

| Trigger | Expected Response |
|---|---|
| Driver license `expiration_date` is today or in the past | `LicenseInspectorSubAgent` halts before any create call; agent reports the license is expired. |
| Extracted `plate_number` / `license_number` / supplier `name` already exists (pre-check hit) | `PreSearchDuplicateSubAgent` halts before any create call; agent reports the existing record. |
| Backend returns `409` despite a clean pre-check (race condition) | Agent re-runs the `get_*_tool` lookup once to surface the conflicting record, then aborts — no retry of the create call. |
| Vision extraction can't parse the image (blurry, wrong document type, unsupported language) | Agent halts, states which fields/document it couldn't read, and asks for a clearer photo. No record is created with blank or guessed fields. |
| A backend-required field has no extracted value (e.g. `fuel_type`) | Agent asks the user for the missing field in-chat and waits for a reply before calling `create_vehicle_tool`. |
| Caller JWT role is `driver` or `mechanic` and intent is Onboard | Agent refuses before calling any `create_*_tool`; no backend round-trip is made for the refusal itself. |
| JWT missing, malformed, or expired | Agent halts before intent classification reaches any tool call and reports an authentication failure. |
| Attached file is not JPEG/PNG (e.g. PDF, HEIC) | Agent rejects the upload before invoking any vision skill and asks for a JPEG/PNG image. |
| Query requested for an entity outside Vehicles/Drivers/Suppliers | Router matches neither Onboard nor a supported Query path; agent reports the request is out of scope. |
| Extracted `vin` / `plate_number` / `license_number` / supplier `name` is empty after sanitization | Treated as a failed extraction — halt and ask for a clearer photo; `create_*_tool` is never called with an empty required field. |

---

## Acceptance Criteria

1. **Given** an admin or fleet_manager uploads a clear license photo with a
   future `expiration_date` and a `license_number` not already on file, **when** the
   onboarding workflow runs, **then** a new Driver is created via `create_driver_tool`
   and the agent confirms it back to the user.
2. **Given** a license photo with a past `expiration_date`, **when** the onboarding
   workflow runs, **then** `LicenseInspectorSubAgent` halts before any create call and
   the agent reports the license as expired.
3. **Given** an extracted `plate_number` that already exists for the organization,
   **when** `PreSearchDuplicateSubAgent` runs, **then** the workflow halts before
   `create_vehicle_tool` is called and the agent reports the existing vehicle.
4. **Given** the backend still returns `409` after a clean duplicate pre-check,
   **when** a `create_*_tool` is called, **then** the agent re-checks once via the
   matching `get_*_tool`, reports the conflicting record, and does not retry the
   create call.
5. **Given** a vehicle document photo that doesn't state fuel type, **when**
   extraction completes with `fuel_type` unset, **then** the agent asks the user for
   `fuel_type` in-chat and only calls `create_vehicle_tool` after receiving it.
6. **Given** a caller whose JWT role is `driver` or `mechanic`, **when** they submit an
   onboarding (write) request, **then** the agent refuses to call any `create_*_tool`
   without a backend round-trip.
7. **Given** a caller of any of the four roles, **when** they submit a read/query
   request, **then** the agent calls the matching `get_*_tool` and returns results
   scoped to the caller's `organization_id`.
8. **Given** an uploaded image is blurry or an unsupported document type, **when** the
   vision extraction skill runs, **then** the agent halts, states what it couldn't
   read, and asks for a clearer photo — no record is created.
9. **Given** an uploaded file is not JPEG/PNG, **when** the onboarding request is
   received, **then** the agent rejects it before invoking any vision skill.
10. **Given** a photographed supplier invoice/registration document, **when** the
    onboarding workflow runs with `extract_supplier_doc`, **then** a new Supplier is
    created via `create_supplier_tool` following the same extract → sanitize →
    duplicate-check (by `name`) → create sequence as vehicles/drivers.
11. **Given** the MCP tool wrappers (`get_*`/`create_*` for vehicles, drivers,
    suppliers) and the three vision extraction skills, **when** the test suite runs,
    **then** all are covered by `pytest` tests using mocked backend/vision responses —
    no live backend or live LLM call is required for the suite to pass.
