# Plan 00 — Foundation Layer (Organization, User, Driver, Vehicle, Supplier, Auth, RBAC)

**Problem source:** [`backendPlan.md`](../backendPlan.md#foundation-layer--entities-attributes-relationships--rbac) § Foundation layer
**Module conventions:** [`backend/CLAUDE.md`](../CLAUDE.md) §§ Multi-tenancy and audit, Role-based access control

**One-line goal:** stand up the tenant boundary (`Organization`), the auth-only login record (`User`), the operational driver profile (`Driver`, deliberately separate from `User`), the physical asset (`Vehicle`), the vendor (`Supplier`), JWT auth, and the two-level RBAC enforcement (`require_role` route dependency + row-level "own records" filtering) that every other plan (01–05) depends on.

**This plan must be built first.** Every other plan assumes these models, the auth dependency, and the RBAC dependencies already exist.

---

## 1. Models — `app/models/foundation.py`

### `Organization`

| Field | Type | Notes |
|---|---|---|
| `id` | `UUID` (pk) | |
| `name` | `str` | |
| `slug` | `str`, unique | URL/subdomain-safe |
| `subscription_tier` | `enum(trial, starter, pro, enterprise)` | |
| `created_at` | `datetime` server_default=now | |

Not org-scoped itself — it *is* the tenant boundary. Every other model FKs to it via `OrgScopedMixin`.

### `User` — authentication only, not an operational profile

| Field | Type | Notes |
|---|---|---|
| `id` | `UUID` (pk) | |
| `organization_id` | `UUID` FK → `organizations.id` | |
| `email` | `str` | unique **per organization**, not globally |
| `hashed_password` | `str` | bcrypt |
| `full_name` | `str` | |
| `phone` | `str`, nullable | |
| `role` | `enum(admin, fleet_manager, driver, mechanic)` | drives `require_role` checks |
| `is_active` | `bool` default `True` | deactivate without deleting |
| `last_login_at` | `datetime`, nullable | |

**Deliberately excludes** license number, license expiry, or any operational field — those live on `Driver`. Do not add them here even if convenient; that's what `Driver` is for.

### `Driver` — operational profile, separate from `User`

| Field | Type | Notes |
|---|---|---|
| `id` | `UUID` (pk) | |
| `organization_id` | `UUID` FK → `organizations.id` | |
| `user_id` | `UUID` FK → `users.id`, **nullable, unique when set** | only present if this driver has app login |
| `full_name` | `str` | |
| `license_number` | `str` | |
| `license_expiry` | `date` | |
| `phone` | `str` | |
| `status` | `enum(active, suspended, inactive)` | |

`user_id` nullable is load-bearing: a fleet manager can register a driver's license/phone before that driver ever gets a login, and some drivers never need one (someone else logs their trips). **Never assume `role = driver` implies a `Driver` row exists, and never assume a `Driver` row implies `user_id` is set** — both directions are optional.

### `Vehicle`

| Field | Type | Notes |
|---|---|---|
| `id` | `UUID` (pk) | |
| `organization_id` | `UUID` FK → `organizations.id` | |
| `plate_number` | `str` | unique per org |
| `make` / `model` / `year` | `str` / `str` / `int` | |
| `vin` | `str`, unique | |
| `current_odometer` | `int` | mutated as a side effect by `FuelLog`, `TripLog`, `MaintenanceLog` creation across Plans 01/03/04 |
| `fuel_type` | `enum(diesel, petrol, hybrid, electric)` | |
| `status` | `enum(active, maintenance, retired)` | |
| `service_interval_km` | `int`, nullable | drives Plan 03's `next_due_km` |
| `service_interval_months` | `int`, nullable | drives Plan 03's `next_due_date` |

### `Supplier`

| Field | Type | Notes |
|---|---|---|
| `id` | `UUID` (pk) | |
| `organization_id` | `UUID` FK → `organizations.id` | |
| `name` / `contact_email` / `phone` | `str` | |
| `avg_lead_time_days` | `int`, nullable | manual, informational |
| `reliability_score` | `numeric(4,3)`, nullable | **computed in Plan 02**, not written here — defined on this model because it's a foundation entity, but the computation lives in `inventory`/`supplier` services |

All four org-scoped models (`User`, `Driver`, `Vehicle`, `Supplier`) inherit `OrgScopedMixin`; `User`/`Driver`/`Vehicle`/`Supplier` also inherit `AuditMixin` except where it would be circular (`User.created_by` — the very first admin user in an org is created by the registration flow itself, not by another `User`; make `created_by` nullable on `User` specifically for this reason).

**Migration order:** `organizations` → `users` → (`drivers`, `vehicles`, `suppliers`, any order — no FKs between these three).

---

## 2. Relationships — enforce exactly as specified, do not "clean up"

- **`Organization` → `User`/`Vehicle`/`Driver`/`Supplier`: 1:N.** The tenant isolation boundary.
- **`User` ↔ `Driver`: 1:0..1, optional, via nullable `Driver.user_id`.** Not the reverse — `User` has no `driver_id` column; look up via `Driver.user_id == user.id`.
- **`Driver` ↔ `Vehicle`: many-to-many, expressed *only* through `TripLog` rows — no FK between them.** Do not add `Driver.vehicle_id` or `Vehicle.driver_id`. If a fast "who's on truck #7 right now" lookup is needed later, that's the flagged-but-not-adopted `Vehicle.assigned_driver_id` from `backendPlan.md`'s open design decisions — raise it explicitly before adding, don't add it as an implementation convenience.
- **`Vehicle` ↔ `ComplianceRule`: soft match by `(make, model, service_type)`, no FK** (Plan 03).
- **`Supplier` → `PartsInventory`/`PurchaseOrder`: 1:N** (Plan 02).

---

## 3. Schemas — `app/schemas/foundation.py`, `app/schemas/auth.py`

- `OrganizationCreate` (registration-only, not a standalone CRUD schema — see §5.1) / `OrganizationResponse`.
- `UserResponse` — never includes `hashed_password`. `role` and `organization_id` are read-only after creation.
- `DriverCreate` / `DriverUpdate` / `DriverResponse` — `user_id` settable only by `admin`/`fleet_manager` (linking an existing `User` to a `Driver` profile), never by the driver themself.
- `VehicleCreate` / `VehicleUpdate` / `VehicleResponse`.
- `SupplierCreate` / `SupplierUpdate` / `SupplierResponse` — `reliability_score` is response-only, never accepted on create/update (owned by Plan 02).
- `RegisterRequest` — `organization_name, organization_slug, admin_email, admin_password, admin_full_name` → creates both `Organization` and its first `User` (`role=admin`) atomically.
- `LoginRequest` — `email, password`. **Note:** since email is unique per-org, not globally, login must resolve the organization first — either via a separate `org_slug` field in the request, or by requiring email to be looked up across all orgs and disambiguated some other way. **Decide this explicitly** (recommended: `LoginRequest` includes `org_slug`) rather than silently assuming global email uniqueness that contradicts the schema.
- `TokenResponse` — `access_token, token_type, expires_in`.
- `MeResponse` — current `User` fields + `organization` summary + `driver_profile: DriverResponse | None` if linked.

---

## 4. Service layer

### 4.1 `app/services/auth_service.py`

```python
async def register_organization(db, data: RegisterRequest) -> tuple[Organization, User]:
    """
    Single transaction:
      1. Insert Organization (slug must be globally unique -- validate before insert).
      2. Insert User with role='admin', organization_id = the new org's id,
         created_by = null (bootstrap case -- see model note above).
      3. Commit both together.
    """

async def authenticate(db, org_slug: str, email: str, password: str) -> User:
    """
    1. Resolve Organization by slug -- 404 if missing.
    2. Fetch User by (organization_id, email) -- reject (401, generic message,
       do not reveal whether the org/email/password was the wrong part) if missing,
       inactive, or password hash mismatch.
    3. Update last_login_at.
    """

def create_access_token(user: User) -> str:
    """JWT claims: sub=user.id, org=user.organization_id, role=user.role, exp.
    Role and org_id are claims read by every downstream dependency -- never re-fetched
    from the DB per request just to check role (fetch the User row for anything else
    the request needs, but trust the JWT claim for the role gate itself)."""
```

### 4.2 `app/services/vehicle_service.py`, `driver_service.py`, `supplier_service.py` (foundation CRUD, RBAC-gated per §6)

Standard org-scoped CRUD (`create`, `get`, `list`, `update`, soft-`delete`) for each. Nothing domain-specific here — Plans 01–05 read these models but do not own their CRUD.

---

## 5. Core auth/RBAC infrastructure — `app/core/deps.py`

```python
async def get_current_user(token: str = Depends(oauth2_scheme), db = Depends(get_db)) -> User:
    """Decodes the JWT, loads the User by (sub, org claim), 401 if invalid/inactive."""

def require_role(*roles: UserRole):
    """
    Returns a FastAPI dependency. Usage: Depends(require_role("admin", "fleet_manager")).
    Reads role directly from the decoded JWT claim (via get_current_user), raises 403
    if current_user.role not in roles. This is the ONLY place role-gating logic lives --
    no router or service function re-implements this check inline.
    """

async def get_current_driver_profile(current_user: User = Depends(get_current_user), db = Depends(get_db)) -> Driver | None:
    """
    Looks up Driver where Driver.user_id == current_user.id, organization-scoped.
    Returns None if current_user.role != 'driver' or no Driver row is linked yet --
    callers that need row-level 'own only' filtering must handle the None case
    explicitly (e.g. return an empty list rather than crashing) rather than assuming
    every role='driver' User has a Driver profile.
    """
```

**Row-level filtering pattern used by every "own only" / "own jobs" route in Plans 01–04:**

```python
async def list_fuel_logs(db, org_id, current_user, driver_profile: Driver | None, ...):
    query = base_query.filter(FuelLog.organization_id == org_id, FuelLog.is_deleted == False)
    if current_user.role == "driver":
        if driver_profile is None:
            return []  # a driver-role user with no linked Driver profile owns nothing
        query = query.filter(FuelLog.driver_id == driver_profile.id)
    # fleet_manager and admin see everything in-org; mechanic has no access to this domain at all
    # (enforced by require_role on the route, not by this filter)
    ...
```

This pattern (org-scope always, then an additional identity filter only for the roles the permission matrix restricts) is what every "own only"/"own jobs" requirement in Plans 01–04 must implement — do not reimplement it ad hoc per domain.

---

## 6. RBAC permission matrix (source of truth — from `backendPlan.md`)

| Domain | Admin | Fleet Manager | Driver | Mechanic |
|---|---|---|---|---|
| Vehicles, Drivers, Suppliers | full | full | read-only | read-only |
| FuelLog, TripLog, DriverReport | full | read all | own only | — |
| MaintenanceLog, MechanicReport | full | read all | — | own jobs |
| PartsInventory, PurchaseOrders | full | full | — | read-only |
| ComplianceRule | full | full | — | read-only |
| Dashboard/insights | full | full | — | — |

Read this table literally: `fleet_manager` has **read all**, not full, on `FuelLog`/`TripLog`/`DriverReport`/`MaintenanceLog`/`MechanicReport` — i.e. a fleet manager cannot create a fuel log or maintenance log through this permission table as written. If product intent differs from this literal reading, that's a decision to confirm before implementing Plans 01/03/04's `require_role` lists, not something to silently "fix" by granting fleet managers write access.

`IncidentLog` is **not listed explicitly** in this matrix (`backendPlan.md`'s Problem 4 narrative says "manager or driver logs an incident," implying both can create). Treat this as an open item to confirm — flag it the same way as the Foundation layer's "Open design decisions," don't silently pick an interpretation in Plan 04.

---

## 7. Routes — `app/api/auth.py`, `app/api/vehicles.py`, `app/api/drivers.py`, `app/api/suppliers.py`

### Auth (no role gate — these routes establish identity)

| Method | Path | Handler |
|---|---|---|
| POST | `/api/v1/auth/register` | `register_organization` |
| POST | `/api/v1/auth/login` | `authenticate` + `create_access_token` |
| GET | `/api/v1/auth/me` | `get_current_user` (+ linked driver profile) |

### Vehicles — `admin`/`fleet_manager` full, `driver`/`mechanic` read-only

| Method | Path | Roles allowed |
|---|---|---|
| GET | `/api/v1/vehicles` | all four roles |
| POST | `/api/v1/vehicles` | `admin`, `fleet_manager` |
| GET | `/api/v1/vehicles/{id}` | all four roles |
| PUT | `/api/v1/vehicles/{id}` | `admin`, `fleet_manager` |
| DELETE | `/api/v1/vehicles/{id}` | `admin`, `fleet_manager` |
| GET | `/api/v1/vehicles/{id}/timeline` | all four (Plan 04 owns the logic) |
| GET | `/api/v1/vehicles/{id}/compliance` | all four (Plan 03 owns the logic) |

### Drivers — same pattern as Vehicles

| Method | Path | Roles allowed |
|---|---|---|
| GET | `/api/v1/drivers` | all four roles |
| POST | `/api/v1/drivers` | `admin`, `fleet_manager` |
| GET | `/api/v1/drivers/{id}` | all four roles |
| PUT | `/api/v1/drivers/{id}` | `admin`, `fleet_manager` |
| DELETE | `/api/v1/drivers/{id}` | `admin`, `fleet_manager` |
| GET | `/api/v1/drivers/{id}/timeline` | all four (Plan 04 owns the logic) |

### Suppliers — same pattern

| Method | Path | Roles allowed |
|---|---|---|
| POST | `/api/v1/suppliers` | `admin`, `fleet_manager` |
| GET | `/api/v1/suppliers` | all four roles |
| PUT | `/api/v1/suppliers/{id}` | `admin`, `fleet_manager` |

---

## 8. Tests

- `test_register_creates_org_and_admin_user` — atomic; force a failure after org creation, assert neither persisted.
- `test_login_requires_correct_org_scope` — two orgs with the same email string, distinct passwords, each logs in only to their own org.
- `test_login_rejects_inactive_user`.
- `test_jwt_contains_org_and_role_claims`.
- `test_require_role_rejects_wrong_role` — a `driver`-role token hitting an `admin`-only route gets `403`, not `401`.
- `test_driver_profile_lookup_returns_none_when_unlinked` — a `role=driver` `User` with no matching `Driver.user_id` row.
- `test_driver_row_level_filter_empty_when_no_profile` — a linked-less driver lists zero `FuelLog`s rather than erroring.
- `test_vehicle_crud_role_gating` — `driver`/`mechanic` get `403` on `POST`/`PUT`/`DELETE`, `200` on `GET`.
- `test_org_scoping_on_email_uniqueness` — same email string across two orgs both register successfully.
- `test_driver_without_user_id_can_be_created` — admin registers a driver profile with no login.
- `test_user_created_by_nullable_for_bootstrap_admin`.

---

## 9. Explicit non-goals

- Any operational field on `User` (license, phone-as-primary-contact for drivers, etc.) — belongs on `Driver`.
- A `Driver.vehicle_id`/`Vehicle.driver_id` FK — explicitly rejected in favor of `TripLog`-based association (Plan 04).
- Mechanic as a structured entity (mirroring `Driver`) — `MaintenanceLog.mechanic_name` stays free text per `backendPlan.md`'s flagged-but-not-adopted decision.
- Multi-supplier-per-part (`PartSupplier` join table) — `PartsInventory` keeps a single primary `supplier_id` until this is explicitly revisited.
