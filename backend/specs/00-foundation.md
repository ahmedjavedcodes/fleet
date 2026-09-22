# Spec 00 — Foundation Layer (Organization, User, Driver, Vehicle, Supplier, Auth, RBAC)

**Derived from:** [`backendPlan.md`](../backendPlan.md#foundation-layer--entities-attributes-relationships--rbac) § Foundation layer · [`plans/00-foundation.md`](../plans/00-foundation.md)
**Status:** Ready for execution — **build first**
**Depends on:** nothing (this is the base layer). Everything else (Specs 01–05) depends on this.

---

## 1. Problem Statement

Every domain in this system — fuel, parts, maintenance, accountability, dashboards — needs the same three things underneath it: a tenant boundary so one fleet operator's data never touches another's, a way to know who is making a request and what they're allowed to do, and a stable set of core entities (people, vehicles, vendors) that domain data attaches to. Without this layer settled first, every downstream problem either duplicates ad hoc auth logic or leaves gaps where one organization's data leaks into another's, or where a driver can read another driver's fuel logs. This layer exists so that never has to be solved twice.

A specific real-world wrinkle drives the `User`/`Driver` split: a fleet manager routinely knows a driver's license number and phone before that driver ever gets an app login — sometimes the driver never gets one at all, with someone else logging trips on their behalf. A single merged "driver" entity can't represent "has an operational profile but no login," so the system needs two entities linked optionally, not one.

---

## 2. Functional Requirements

| ID | Requirement |
|---|---|
| FR-0.1 | The system shall support multiple organizations (tenants), each fully isolated from every other. |
| FR-0.2 | The system shall allow registering a new organization together with its first `admin` user in one operation. |
| FR-0.3 | The system shall issue a JWT on successful login containing the user's identity, organization, and role. |
| FR-0.4 | The system shall enforce four roles — `admin`, `fleet_manager`, `driver`, `mechanic` — with a fixed permission matrix (§4) governing access to every domain. |
| FR-0.5 | The system shall model `User` as an authentication-only record and `Driver` as a separate operational profile, linked by an optional `user_id`. |
| FR-0.6 | The system shall allow creating a `Driver` profile with no linked `User` (no login access). |
| FR-0.7 | The system shall allow CRUD on `Vehicle`, `Driver`, and `Supplier`, gated by role per the permission matrix. |
| FR-0.8 | The system shall express the `Driver`↔`Vehicle` relationship only through trip history (Spec 04), never via a direct foreign key. |
| FR-0.9 | The system shall reject any request whose JWT role is not permitted for the target route, before any handler logic runs. |
| FR-0.10 | The system shall, for routes marked "own only"/"own jobs" in the permission matrix, filter results to the authenticated user's own driver identity in addition to organization scope. |

---

## 3. Behaviour

### 3.1 Registration (`POST /auth/register`)

1. Validate the requested `organization_slug` is globally unique.
2. Insert `Organization`.
3. Insert `User` with `role=admin`, linked to the new organization, `created_by=null` (bootstrap case — no prior user exists to attribute authorship to).
4. Both inserts commit as one transaction; either failing rolls back both.

### 3.2 Login (`POST /auth/login`)

1. Resolve the target organization (email is unique **per organization**, not globally — the login request must disambiguate which org, e.g. via an `org_slug` field).
2. Look up the `User` by `(organization_id, email)`.
3. Verify `is_active` and the password hash. On any failure, return a generic `401` — never reveal which part (org/email/password) was wrong.
4. Update `last_login_at`.
5. Issue a JWT with `sub=user.id`, `org=organization.id`, `role=user.role`, an expiry.

### 3.3 Route-level RBAC

1. Every protected route declares its allowed roles via a `require_role(...)` dependency.
2. The dependency decodes the JWT (via `get_current_user`), checks `role` against the allowed set, and raises `403` before the route handler body executes.
3. No router or service function re-implements this check inline — it is centralized in one dependency.

### 3.4 Row-level RBAC ("own only" / "own jobs")

1. For domains marked `driver: own only` or `mechanic: own jobs` in the permission matrix, the service layer resolves the caller's own `Driver` profile (`get_current_driver_profile`) via `Driver.user_id == current_user.id`.
2. If no such profile exists (a `driver`-role user not yet linked to a `Driver` row), the query returns an empty result set rather than erroring or returning unfiltered data.
3. This filter is applied **in addition to** standard organization scoping, never in place of it.

### 3.5 Foundation entity CRUD (`Vehicle`, `Driver`, `Supplier`)

- Standard org-scoped, soft-deleting CRUD.
- `admin`/`fleet_manager`: full (create, read, update, delete).
- `driver`/`mechanic`: read-only (`GET` routes only — write routes reject with `403`).

---

## 4. Constraints

1. **Tenant isolation is absolute.** No query, in any domain, ever returns or mutates a row belonging to another `organization_id`.
2. **`User` and `Driver` are never merged.** `User` carries no operational fields (license, driver-specific phone-as-primary-contact); `Driver` carries no auth fields (password, role, last login).
3. **`user_id` on `Driver` is optional in both directions of reasoning:** a `Driver` may have no `User`; a `role=driver` `User` may have no `Driver` yet. Code must never assume either implication holds without checking.
4. **No `Driver`↔`Vehicle` foreign key**, in either direction. The relationship exists solely as a derived view over `TripLog` rows (Spec 04). This is a deliberate, previously-flagged design decision — not an oversight to "fix" by adding an assignment column.
5. **Role-gating logic lives in exactly one place** (`require_role`/`get_current_user`/`get_current_driver_profile` in `app/core/deps.py`). No route handler or service function contains an inline `if current_user.role == ...` access-control check duplicating this.
6. **Email uniqueness is scoped to the organization, not global.** Login must disambiguate organization before checking credentials.
7. **JWT role claim is authoritative for route gating**; it is not re-verified against a fresh DB read on every request purely to re-check the role (though the user's `is_active` status may still need a fresh check depending on token lifetime policy — decide and document this explicitly rather than leaving it implicit).
8. **The permission matrix (§ below) is applied literally.** Where it says `fleet_manager: read all` rather than `full`, fleet managers do not get write access to that domain unless a product decision explicitly overrides the matrix — this must be confirmed, not silently expanded.

### Permission matrix (source of truth)

| Domain | Admin | Fleet Manager | Driver | Mechanic |
|---|---|---|---|---|
| Vehicles, Drivers, Suppliers | full | full | read-only | read-only |
| FuelLog, TripLog, DriverReport | full | read all | own only | — |
| MaintenanceLog, MechanicReport | full | read all | — | own jobs |
| PartsInventory, PurchaseOrders | full | full | — | read-only |
| ComplianceRule | full | full | — | read-only |
| Dashboard/insights | full | full | — | — |

`IncidentLog` is not explicitly listed here — Spec 04 flags this as an open item rather than assuming an interpretation.

---

## 5. Edge Cases and Error Handling

| # | Scenario | Expected behavior |
|---|---|---|
| EC-1 | Registering an organization with a `slug` that already exists | `409`; no `Organization` or `User` row is created. |
| EC-2 | Registration succeeds for the org but fails while creating the admin user | Full rollback — no orphaned `Organization` with zero users. |
| EC-3 | Login with correct email/password but wrong organization | `401` — email is scoped per-org, so this is indistinguishable from "user not found" and must return the same generic message. |
| EC-4 | Login for an `is_active=false` user | `401`, same generic message as a wrong password (don't leak account status). |
| EC-5 | A `driver`-role JWT hits an `admin`-only route (e.g. `POST /vehicles`) | `403`, checked before any handler logic runs — verify via a route that would otherwise succeed if reached. |
| EC-6 | A `driver`-role user with no linked `Driver` profile calls `GET /fuel` | Returns an empty list, not a `500` or unfiltered data. |
| EC-7 | Two organizations each register a user with the identical email string | Both succeed independently — uniqueness is per-org. |
| EC-8 | A `Driver` created with `user_id` pointing to a `User` already linked to a different `Driver` | Rejected — `user_id` is unique when set; one `User` maps to at most one `Driver`. |
| EC-9 | An `admin` attempts to soft-delete a `Vehicle`/`Driver`/`Supplier` referenced by historical domain records (e.g. old `FuelLog`s) | Allowed — soft-delete hides it from active listings but historical records referencing it remain intact and readable. |
| EC-10 | A request with an expired or malformed JWT | `401` on `get_current_user`, before any `require_role` check runs. |
| EC-11 | `mechanic` role attempts to read `PurchaseOrders` (read-only per matrix) vs. attempts to create one | `GET` succeeds, `POST` returns `403`. |

---

## 6. Acceptance Criteria

- [ ] **AC-1:** `POST /auth/register` creates exactly one `Organization` and one `admin` `User`, atomically.
- [ ] **AC-2:** `POST /auth/login` issues a JWT whose decoded claims include `sub`, `org`, and `role` matching the authenticated user.
- [ ] **AC-3:** Login with a valid email/password pair from the wrong organization fails with `401`.
- [ ] **AC-4:** A route protected by `require_role("admin")` rejects `fleet_manager`/`driver`/`mechanic` tokens with `403` and accepts `admin` tokens.
- [ ] **AC-5:** A `driver`-role user calling a "own only" endpoint (e.g. `GET /fuel`) with no linked `Driver` profile receives an empty list, not an error.
- [ ] **AC-6:** A `driver`-role user with a linked `Driver` profile sees only `FuelLog`/`TripLog`/`DriverReport` rows where `driver_id` matches their own profile — never another driver's.
- [ ] **AC-7:** `GET /vehicles`, `/drivers`, `/suppliers` succeed for all four roles; `POST`/`PUT`/`DELETE` on the same routes succeed only for `admin`/`fleet_manager`.
- [ ] **AC-8:** Creating a `Driver` with no `user_id` succeeds and is retrievable.
- [ ] **AC-9:** Creating two `Driver` rows pointing at the same `user_id` fails.
- [ ] **AC-10:** Two different organizations can each register a user with the same email address without conflict.
- [ ] **AC-11:** No endpoint in this layer (or any dependent layer) returns data belonging to another organization, under any role.
