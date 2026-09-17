# Fleet SaaS — Problem Engineering Plan

**Project:** Autonomous Fleet Management SaaS (Phase 3)  
**Scope:** 5 core problems — backend module  
**Constraint:** No real-time hardware, IoT, or GPS. All data enters via manual forms or file uploads.

Before writing a single line of code: what each problem actually is in the real world, why the solution works, how data enters the system, and what the backend must compute versus what it just stores.

---

## The boundary principle

Across all five problems, one rule governs what the backend does and does NOT do:

**Backend performs computations that are deterministic and immediate:**  
cost_per_km (division), next_due_km (addition), stock alerts (comparison), compliance status (subtraction + comparison), supplier reliability (ratio), timeline (UNION + ORDER BY), fleet health (weighted average). These produce the same output for the same input every time — no randomness, no model inference, no probability.

**Everything that requires inference, pattern recognition, forecasting, or natural language** belongs in the `ai_agents` module. The backend stores the data those inferences need, with rich metadata for filtering, and exposes it through clean endpoints that MCP tools can wrap.

Throughout this document, each data flow step is labeled:

- `[MANUAL]` — a human enters data via a form or uploads a file
- `[COMPUTED]` — the backend calculates something deterministic automatically
- `[AI-FUTURE]` — work that belongs in the ai_agents module, built later

---

## Foundation layer — entities, attributes, relationships & RBAC

Every problem below (1 through 5) is built on five foundational entities: `Organization`, `User`, `Driver`, `Vehicle`, `Supplier`. This section defines their attributes, how they relate to each other, and how role-based access control governs who can touch what. The problem sections reference these entities but assume this layer as settled ground — read this first.

### Organization — the tenant boundary

| Field | Type | Notes |
|---|---|---|
| id | UUID (PK) | |
| name | string | |
| slug | string, unique | Used in URLs/subdomains |
| subscription_tier | enum | trial / starter / pro / enterprise |
| created_at | timestamp | |

Every other entity belongs to exactly one Organization via `organization_id` (`OrgScopedMixin`). No entity is ever shared across two organizations — that's the tenant isolation boundary.

### User — the login account (authentication only)

| Field | Type | Notes |
|---|---|---|
| id | UUID (PK) | |
| organization_id | UUID (FK) | |
| email | string, unique per org | |
| hashed_password | string | bcrypt |
| full_name | string | |
| phone | string, nullable | |
| role | enum | admin / fleet_manager / driver / mechanic |
| is_active | bool | Deactivate without deleting |
| last_login_at | timestamp, nullable | |

`User` is deliberately just the authentication record — not a person's full operational profile. It exists so login, JWT issuance, and role enforcement have one clean source of truth. No age/date_of_birth here — a login account doesn't need it.

### Driver — the operational profile (separate from User)

| Field | Type | Notes |
|---|---|---|
| id | UUID (PK) | |
| organization_id | UUID (FK) | |
| user_id | UUID (FK), **nullable** | Only set if this driver has app login access |
| full_name | string | |
| license_number | string | |
| license_expiry | date | |
| phone | string | |
| status | enum | active / suspended / inactive |

`Driver` is split from `User` on purpose: a fleet manager can register a driver's license and phone number before that driver ever gets a login, or a driver may never need login access at all (someone else logs their trips for them). `user_id` being nullable is what makes both cases possible.

### Vehicle — the physical asset

| Field | Type | Notes |
|---|---|---|
| id | UUID (PK) | |
| organization_id | UUID (FK) | |
| plate_number | string, unique per org | |
| make / model / year | string / string / int | |
| vin | string, unique | |
| current_odometer | int | Updated by fuel logs, trips, service logs |
| fuel_type | enum | diesel / petrol / hybrid / electric |
| status | enum | active / maintenance / retired |
| service_interval_km / _months | int / int | Drives maintenance scheduling — Problem 3 |

### Supplier — parts vendor

| Field | Type | Notes |
|---|---|---|
| id | UUID (PK) | |
| organization_id | UUID (FK) | |
| name / contact_email / phone | string | |
| avg_lead_time_days | int | |
| reliability_score | float, computed | Recalculated on every PO receive — Problem 2 |

### Relationships and cardinality

**Organization → User / Vehicle / Driver / Supplier: 1 : N.** One org, many of each — the tenant isolation boundary.

**User ↔ Driver: 1 : 0..1 (optional).** A `User` with `role = driver` typically has one linked `Driver` profile. A `Driver` can exist with `user_id = null` (no login access at all). A `User` with `role = admin` or `fleet_manager` has no `Driver` profile.

**Driver ↔ Vehicle: many-to-many, via `TripLog` — no direct foreign key.** One driver drives many vehicles over time; one vehicle is driven by many drivers over time. Each `TripLog` row is one `(driver, vehicle, time-window)` pairing. There is no cap on either side, and the system does not enforce a fixed driver-vehicle assignment.

**Driver → FuelLog / TripLog / DriverReport / IncidentLog: 1 : N.**

**Vehicle → FuelLog / MaintenanceLog / TripLog / DriverReport / IncidentLog: 1 : N.**

**Vehicle ↔ ComplianceRule: soft match, not a foreign key.** A rule is defined for `(vehicle_make, vehicle_model, service_type)`. Every vehicle matching that make/model inherits the rule automatically — adding a 51st identical truck requires zero new rule rows.

**Supplier → PartsInventory / PurchaseOrder: 1 : N.**

**PartsInventory ↔ PurchaseOrder: many-to-many, but soft (JSONB, not a join table).** Captured in `PurchaseOrder.line_items`.

**MaintenanceLog → MechanicReport: 1 : 0..1.**

### Role-based access control

`User.role` is one of `admin`, `fleet_manager`, `driver`, `mechanic`. Enforcement happens at two levels:

1. **Route-level** — a `require_role([...])` dependency rejects with 403 before the router body runs, based on the JWT's role claim.
2. **Row-level** — on routes a `driver` or `mechanic` *can* reach, the service layer filters to their own records (`WHERE driver_id = current_user.driver_profile.id`), on top of the standard org-scope filter.

| Domain | Admin | Fleet Manager | Driver | Mechanic |
|---|---|---|---|---|
| Vehicles, Drivers, Suppliers | full | full | read-only | read-only |
| FuelLog, TripLog, DriverReport | full | read all | own only | — |
| MaintenanceLog, MechanicReport | full | read all | — | own jobs |
| PartsInventory, PurchaseOrders | full | full | — | read-only |
| ComplianceRule | full | full | — | read-only |
| Dashboard/insights | full | full | — | — |

### Open design decisions (flagged, not yet adopted)

- **No "currently assigned vehicle" field.** `Vehicle.assigned_driver_id` (nullable FK to `Driver`) would give a fast "who's on truck #7 today" lookup, distinct from `TripLog` history. Not added to the schema until decided.
- **Mechanic has no dedicated entity.** `MaintenanceLog.mechanic_name` is free text, not a FK — unlike `Driver`, there's no structured profile for mechanic performance tracking. Mirroring the `Driver` pattern is an option, not yet adopted.
- **PartsInventory ties one part to one primary Supplier.** Real purchasing sometimes multi-sources a part. A `PartSupplier` join table would support that; not added until needed.

---

## Problem 1 — Fuel price volatility

*Fleet managers are bleeding money and don't know where it's going.*

### What this problem actually is

A fleet of 20 trucks consumes thousands of liters of diesel per month. Petroleum prices in Pakistan fluctuate week to week — sometimes day to day. The fleet manager has a monthly budget, but he has no idea which trucks cost more to run, whether a truck's consumption has spiked (leaking fuel line? driver siphoning?), or what next month's fuel cost will look like. He has a pile of paper receipts from different stations with different prices. The data exists, but it's in a drawer, not in a system.

### What the optimized solution is

The solution is not "store fuel logs." It's **turn every fill-up into a cost-per-kilometer data point**. That one computed number — how many rupees per kilometer this truck costs to run — is what transforms a receipt pile into actionable intelligence. Once you have cost-per-km per vehicle over time, anomalies become visible (truck #7 jumped from ₹18/km to ₹26/km this month), trends become forecastable (fleet average is rising 3% month-over-month), and budget forecasting becomes possible (at current rates, next month costs ₹X).

### How data enters the system

1. `[MANUAL]` **Driver fills the tank.** At the fuel station. He sees: liters pumped, price per liter, total bill, and his truck's odometer reading. These four numbers are the raw input.

2. `[MANUAL]` **Driver logs the fill-up in the app.** Frontend form: vehicle (dropdown), date, odometer reading, liters filled, price per liter, total cost, station name (optional). Takes 30 seconds. Alternatively, driver photographs the receipt and uploads it — the AI module parses it later.

3. `[COMPUTED]` **Backend computes cost_per_km.** This is where the value lives. The service layer fetches the previous FuelLog for this vehicle, computes the odometer delta (distance driven since last fill-up), and divides total_cost by that delta: `cost_per_km = total_cost / (current_odometer - previous_odometer)`. First fill-up for a vehicle has no previous record — cost_per_km is null. This is not AI — it's division.

4. `[COMPUTED]` **Backend updates vehicle odometer.** If the new odometer reading is higher than the vehicle's current_odometer, update it. This keeps the vehicle's mileage current without a separate "update odometer" workflow — it happens as a side effect of logging fuel.

5. `[COMPUTED]` **Backend flags anomalies.** Compare this fill-up's cost_per_km against the vehicle's 3-month rolling average. If it deviates by more than 20%, mark it as anomalous in the response. This is a simple comparison, not AI — but it catches fuel leaks, siphoning, or routing changes immediately.

6. `[AI-FUTURE]` **AI module forecasts and cross-references.** Not built in backend. Later, the FuelAnalysis agent queries this data via MCP, forecasts next month's budget from trends, and cross-references anomalies with mechanic notes via RAG ("was fuel line leak reported for this truck?").

### Models and why each exists

| Model | Why it exists |
|-------|---------------|
| `FuelLog` | Every fill-up = one row. The core data point. Stores raw inputs (liters, price, odometer) + computed output (cost_per_km). |
| `FuelReceipt` | Uploaded receipt image/PDF. Stored with status=pending. AI parses it later. One receipt per fuel log. |
| `Vehicle` | Provides current_odometer for the delta calculation. Updated as side effect of fuel logging. |
| `Driver` | Links the fill-up to who was driving. Enables per-driver fuel analysis. |

### Backend principles applied

**Computed fields on create, not on read.** cost_per_km is calculated when the FuelLog is created, not when it's queried. This means every list/get is fast (no joins needed to compute), and the computed value is frozen at creation time — it won't change retroactively if someone edits a previous record. Store the computation result, not the formula.

**Side-effect updates scoped to a single transaction.** Creating a FuelLog also updates Vehicle.current_odometer — both happen in the same database transaction. If either fails, both roll back. This prevents orphaned state where the fuel log exists but the vehicle odometer is stale.

**Anomaly detection as a comparison, not a model.** The 20% deviation check is a simple comparison against a rolling average, run on create. It's not machine learning, it's not AI — it's a WHERE clause and some arithmetic. Don't over-engineer detection that division can handle.

**File storage separated from data parsing.** The backend stores the receipt file and tracks its processing status. It does NOT parse the receipt — that's the AI module's job. Backend is a storage and status layer for files. This keeps the backend simple and keeps the AI boundary clean.

### Routes

| Method | Path | Purpose |
|--------|------|---------|
| POST | `/api/v1/fuel` | Create fuel log → computes cost_per_km, updates odometer, checks anomaly |
| GET | `/api/v1/fuel` | List fuel logs — filterable by vehicle_id, driver_id, date range |
| GET | `/api/v1/fuel/{id}` | Get single fuel log with receipt info |
| PUT | `/api/v1/fuel/{id}` | Update fuel log — recalculates cost_per_km |
| POST | `/api/v1/fuel/{id}/receipt` | Upload receipt file (multipart) → stores file, sets status=pending |
| GET | `/api/v1/fuel/summary` | Monthly aggregation: total cost, avg cost_per_km, per vehicle — feeds dashboard |

---

## Problem 2 — Unpredictable spare parts

*The part you need is never in stock when the truck breaks down.*

### What this problem actually is

A truck breaks down. The mechanic diagnoses a failed alternator belt. The fleet manager checks the parts shelf — empty. He calls the supplier — "2-3 weeks for import." The truck sits idle for 3 weeks because nobody tracked that they'd used the last alternator belt two months ago. Meanwhile, another supplier could have delivered in 5 days, but nobody tracks supplier performance either. The problem isn't that parts are expensive — it's that the fleet has zero visibility into what's in stock, how fast it's being consumed, and which supplier actually delivers on time.

### What the optimized solution is

Three interlocking mechanisms, all deterministic:

**(a) Stock threshold alerts** — every part has a reorder_threshold. Every time stock decreases (part used in a repair), check if qty_on_hand dropped below it. This is a simple comparison, not AI.

**(b) Consumption linkage** — every part consumed is linked to a specific maintenance event via MechanicReport.parts_used. This creates consumption velocity data: "we use 3 alternator belts per month across the fleet." The AI forecasting agent uses this later.

**(c) Supplier reliability scoring** — when a purchase order is marked as received, the system computes the delivery delta (actual_delivery - expected_delivery) and updates the supplier's reliability score. Over time, you know which supplier delivers on time and which doesn't.

### How data enters the system

1. `[MANUAL]` **Admin registers parts in inventory.** Part number, name, compatible vehicle makes/models, current quantity, reorder threshold, unit cost, supplier. This is the initial stock count — a one-time data entry when the system is set up, then maintained as parts arrive and are consumed.

2. `[MANUAL]` **Mechanic uses parts in a repair.** When a mechanic submits a MechanicReport, the parts_used field contains `[{part_id, qty}]`. This is the consumption event. The mechanic selects which parts and how many — it's part of the repair logging workflow, not a separate step.

3. `[COMPUTED]` **Backend decrements stock + checks threshold.** When a MechanicReport is created, the service layer loops through parts_used, decrements PartsInventory.qty_on_hand for each, and checks if the new qty is below reorder_threshold. If yes, the response includes a low_stock_alert flag. No background job, no queue — it's a synchronous check on write.

4. `[MANUAL]` **Admin creates a purchase order.** When stock is low, the fleet manager places an order. They enter: supplier, parts needed (line items with part_id, qty, unit_price), expected delivery date.

5. `[MANUAL]` **Admin marks purchase order as received.** When the shipment arrives, the admin hits "Receive" (PATCH endpoint). This is a manual trigger with automated side effects.

6. `[COMPUTED]` **Backend increments stock + updates supplier score.** On receive: (1) set actual_delivery = today, status = received; (2) for each line item, increment PartsInventory.qty_on_hand; (3) recalculate `Supplier.reliability_score = count(on_time_orders) / count(total_orders)` where on_time = actual_delivery ≤ expected_delivery. All in one transaction.

7. `[AI-FUTURE]` **AI forecasts future demand.** PartsForecasting agent queries consumption history via MCP: "3 alternator belts used across the fleet in the last 90 days. At this rate, stock will hit zero in 45 days. Best supplier (by reliability) has a 10-day lead time. Recommend ordering by day 35."

### Models and why each exists

| Model | Why it exists |
|-------|---------------|
| `PartsInventory` | Current stock state. qty_on_hand and reorder_threshold make the alert system work. compatible_vehicles (JSONB array) lets the AI agent check "do we have brake pads for a Toyota Hilux?" in one query. |
| `Supplier` | Vendor identity + computed reliability_score. Without this, the fleet manager can't make data-driven supplier decisions. |
| `PurchaseOrder` | The full order lifecycle (pending → shipped → received → cancelled). The delta between expected and actual delivery feeds supplier scoring. line_items (JSONB) links which parts were ordered and at what price. |
| `MechanicReport` | Already exists for Problem 3 — its parts_used field is the consumption event that decrements inventory. This is the link between maintenance and inventory domains. |

### Backend principles applied

**Event-driven side effects within a single transaction.** Stock decrement happens inside the MechanicReport creation transaction. Stock increment happens inside the PurchaseOrder receive transaction. No message queues, no eventual consistency — one database transaction, all or nothing. For a SaaS at this scale, transactional consistency is more valuable than async complexity.

**Threshold-based alerting — comparison on write, not polling.** Don't run a background job that checks stock levels every hour. Instead, check on every write that changes qty_on_hand. The alert is a return value, not a notification system. The frontend reads the flag and shows a banner. Simple, immediate, no infrastructure.

**Supplier scoring as a rolling computation.** reliability_score is recalculated every time a PurchaseOrder is received. It's a ratio: on_time_deliveries / total_completed_orders. Store the score on the Supplier row, recompute on each receive event.

**JSONB for flexible line items.** PurchaseOrder.line_items is JSONB, not a separate join table. At this scale (dozens of orders, not millions), the query simplicity outweighs the normalization benefit.

### Routes

| Method | Path | Purpose |
|--------|------|---------|
| POST | `/api/v1/inventory` | Register a part in inventory |
| GET | `/api/v1/inventory` | List all parts — filterable by category, supplier, compatible vehicle |
| PUT | `/api/v1/inventory/{id}` | Update part details (manual stock adjustment also goes here) |
| GET | `/api/v1/inventory/low-stock` | All parts where qty_on_hand < reorder_threshold — the "order now" list |
| POST | `/api/v1/suppliers` | Register a supplier |
| GET | `/api/v1/suppliers` | List suppliers — sortable by reliability_score |
| PUT | `/api/v1/suppliers/{id}` | Update supplier details |
| POST | `/api/v1/purchase-orders` | Create purchase order with line items |
| GET | `/api/v1/purchase-orders` | List orders — filterable by status, supplier, date range |
| PUT | `/api/v1/purchase-orders/{id}` | Update order details |
| PATCH | `/api/v1/purchase-orders/{id}/receive` | Mark received → increments stock, scores supplier. The most important endpoint in this domain. |

---

## Problem 3 — Breakdowns, maintenance & compliance (merged)

*Every repair is a surprise because nobody tracks service schedules, and manufacturer guidelines exist but nobody checks if the fleet follows them.*

### What this problem actually is

This is two sides of the same coin that were originally separated as "Frequent Breakdowns" and "Compliance & Manufacturer Guidelines" — but they share the same data, the same computation, and the same output. Here's why:

**The breakdown side:** The manufacturer says change oil every 10,000 km. Replace timing belt at 80,000 km. The fleet manager has 20 trucks at different mileages, serviced at different times. He's tracking this on paper or not at all. A truck hits 95,000 km without the timing belt being replaced, the belt snaps, the engine is damaged — ₹200,000 repair that a ₹5,000 belt change would have prevented.

**The compliance side:** The same manufacturer schedule exists in a PDF manual sitting in a drawer. With 20 vehicles from 3 different manufacturers, manually checking each vehicle against its schedule is impossible. Violations pile up silently until something breaks — and then the warranty claim is rejected because the maintenance schedule wasn't followed.

**Why they're the same problem:** Both ask the identical question — "given this vehicle's current mileage and its last service date, is it due for maintenance?" The breakdown side frames it as "prevent the next breakdown." The compliance side frames it as "follow the manufacturer's rules." The data model, the computation, and the output are identical. One solution serves both.

### What the optimized solution is

Three mechanisms working together:

**(a) Compliance rules define WHAT'S needed.** ComplianceRule stores manufacturer guidelines: "Toyota Hilux requires oil change every 10,000 km or 6 months." These are entered once per vehicle make/model/service-type combination. When you add a new Toyota Hilux to the fleet, it automatically inherits all existing Toyota Hilux rules — no per-vehicle configuration.

**(b) Maintenance logs record WHAT'S been done.** MaintenanceLog captures every service event with the odometer at the time of service and the service type. When a log is created, the backend computes next_due_km and next_due_date from the vehicle's intervals.

**(c) The compliance checker compares the two.** For each vehicle, find all matching ComplianceRules (by make + model). For each rule, find the most recent MaintenanceLog of that service type. Compare the gap (current mileage minus last service mileage) against the rule's interval. Return: compliant, due_soon (within 80% of limit), or overdue.

**Separately:** MechanicReport stores the mechanic's free-text diagnostic notes. The backend stores these as-is. The AI module vectorizes them into Pinecone later for pattern recognition — "alternator belt flagged in 4 of 6 similar trucks" is an AI insight, not a backend computation.

### How data enters the system

1. `[MANUAL]` **Admin enters compliance rules (one-time setup per vehicle type).** For each vehicle make + model + service type, enter the manufacturer's interval in km and months. Example: "Toyota Hilux — oil change — every 10,000 km or 6 months." This is a setup task done once per vehicle type in the fleet. The AI can automate this later by parsing uploaded manufacturer PDF manuals.

2. `[MANUAL]` **Mechanic or manager logs a maintenance event.** After completing a service: vehicle, date, odometer at service, service type (from a fixed enum — oil_change, brake_service, tire_rotation, engine_repair, transmission, electrical, body_work, general_inspection, other), cost, description.

3. `[COMPUTED]` **Backend computes next service due date and mileage.** `next_due_km = odometer_at_service + vehicle.service_interval_km` and `next_due_date = date + vehicle.service_interval_months`. These are frozen at creation time. If the vehicle's intervals change later, existing logs keep their original next_due values — only new logs use the updated intervals.

4. `[MANUAL]` **Mechanic writes a diagnostic report.** Attached to the maintenance log. Four free-text fields: diagnostic_notes (what did you inspect/test), findings (what did you find), actions_taken (what did you fix/replace), recommendations (what should be done next). Plus parts_used (selected from inventory dropdown, triggers stock decrement from Problem 2). This is the data that makes RAG valuable — the mechanic's own words about what they saw.

5. `[COMPUTED]` **Upcoming/overdue endpoints expose scheduling state.** GET /maintenance/upcoming: vehicles where `next_due_km - current_odometer < 1000` (service coming soon). GET /maintenance/overdue: vehicles where `current_odometer > next_due_km OR today > next_due_date`. These are read-time computations — the query compares current vehicle state against stored next_due values.

6. `[COMPUTED]` **Compliance checker computes rule-by-rule status.** When GET /compliance/status/{vehicle_id} is called:
   - Fetch all ComplianceRules matching this vehicle's make + model
   - For each rule, find the latest MaintenanceLog for this vehicle with that service_type
   - Compute `km_gap = vehicle.current_odometer - last_service.odometer_at_service`
   - Compute `months_gap = today - last_service.date`
   - If km_gap > rule.interval_km OR months_gap > rule.interval_months → **overdue**
   - If within 80% of either limit → **due_soon**
   - Otherwise → **compliant**
   - If no MaintenanceLog exists for that service type → **never_performed** (treated as overdue)
   - Returns a list of `{rule, status, km_remaining, days_remaining}`

7. `[AI-FUTURE]` **AI finds cross-vehicle patterns in mechanic notes.** Vectorization pipeline picks up new MechanicReports, embeds the text, upserts to Pinecone with metadata (vehicle_make, service_type, date). MaintenancePrediction agent queries: "any recurring issues on Isuzu NPR trucks?" → semantic search returns similar reports → LLM synthesizes: "alternator belt failures in 4 of 6 NPR trucks this quarter."

8. `[AI-FUTURE]` **AI extracts rules from manufacturer PDFs.** ComplianceMonitor agent parses uploaded manufacturer manuals (vectorized in Pinecone) and extracts service schedules that haven't been entered as ComplianceRules yet. This automates step 1 for future vehicle types.

### Models and why each exists

| Model | Why it exists |
|-------|---------------|
| `ComplianceRule` | The manufacturer's rule. vehicle_make + vehicle_model + service_type is the composite lookup key. One rule per service type per vehicle type. Scoped by make/model so 50 identical trucks share the same 8 rules without per-vehicle duplication. |
| `MaintenanceLog` | The structured service record. Carries the computed next_due_km and next_due_date that make scheduling work. One row per service event per vehicle. The compliance checker queries "most recent MaintenanceLog for this vehicle where service_type = X." |
| `MechanicReport` | The unstructured diagnostic record. Exists as a child of MaintenanceLog (1:1). Separated because: (a) not every maintenance event has a detailed mechanic writeup, and (b) the free-text fields have a different lifecycle — they get vectorized into Pinecone for RAG, which the structured MaintenanceLog doesn't. |
| `Vehicle` | Provides make + model (to match ComplianceRules), service_interval_km + service_interval_months (for next_due computation), and current_odometer (for upcoming/overdue comparison and compliance gap calculation). |

### Backend principles applied

**Computed on write, compared on read.** next_due_km is computed when the MaintenanceLog is created (write-time). Whether the vehicle is overdue is determined when /overdue or /compliance/status is called (read-time comparison). This separates the expensive computation (fetching vehicle intervals, doing arithmetic) from the cheap comparison (a WHERE clause).

**Compliance computed fresh on every read, never stored.** Unlike cost_per_km (computed on write and frozen), compliance status changes over time as mileage increases. A vehicle that was compliant yesterday might be overdue today because it drove 500 km. There's no stale "compliance_status" column that could drift out of sync.

**No service performed ≠ skip the rule.** If no MaintenanceLog exists for a given service type, the rule status is "never_performed" — which is treated as overdue. The absence of data is itself a compliance violation. The query must handle the LEFT JOIN case where the maintenance log is null.

**Rules scoped by make/model, not by individual vehicle.** ComplianceRules are defined for "Toyota Hilux" — not for "Vehicle #7". When you add a new Hilux to the fleet, it automatically inherits all existing Hilux rules. This scales: 50 Hiluxes share the same 8 rules instead of maintaining 400 individual rule assignments.

**Structured data and unstructured data in separate models.** MaintenanceLog has enums, dates, integers — queryable with SQL. MechanicReport has free text — queryable with vector search. Mixing them in one model would mean every SQL query drags along large text columns, and every vector search needs to join back to get structured metadata. Separating them lets each be queried optimally.

**Store text for the AI, don't analyze it yourself.** The backend stores mechanic notes exactly as written. It doesn't try to extract keywords, classify severity, or detect patterns. That's the AI module's job. The backend's contribution is rich metadata on the MechanicReport (via its parent MaintenanceLog → Vehicle) so that Pinecone vectors have good filter dimensions.

### Routes

| Method | Path | Purpose |
|--------|------|---------|
| POST | `/api/v1/maintenance` | Create maintenance log → computes next_due_km and next_due_date |
| GET | `/api/v1/maintenance` | List logs — filterable by vehicle, service_type, date range |
| GET | `/api/v1/maintenance/{id}` | Get log with its mechanic report (eager loaded) |
| PUT | `/api/v1/maintenance/{id}` | Update log — recalculates next_due if odometer or date changed |
| POST | `/api/v1/maintenance/{id}/mechanic-report` | Attach diagnostic report → stores text, decrements parts inventory |
| GET | `/api/v1/maintenance/upcoming` | Vehicles within 1000km of next service — the "schedule now" list |
| GET | `/api/v1/maintenance/overdue` | Vehicles past their service deadline — the "urgent" list |
| POST | `/api/v1/compliance/rules` | Create a manufacturer guideline rule |
| GET | `/api/v1/compliance/rules` | List rules — filterable by make, model, service_type |
| PUT | `/api/v1/compliance/rules/{id}` | Update rule intervals |
| GET | `/api/v1/compliance/status` | Fleet-wide compliance matrix — every vehicle × every applicable rule |
| GET | `/api/v1/compliance/status/{vehicle_id}` | Per-vehicle compliance — all rules with status, km remaining, days remaining |

---

## Problem 4 — Driver accountability & asset misuse

*Nobody knows who had the truck when the damage happened.*

### What this problem actually is

A truck comes back with a dented fender. The fleet manager asks the driver — "wasn't me, it was like that when I got it." The previous driver says the same. There's no record of what condition the vehicle was in when each driver took it or returned it. Separately, a driver is consistently late on deliveries — but without trip timestamps, it's just a feeling, not data. The core issue is absence of an auditable paper trail linking drivers to vehicle states across time.

### What the optimized solution is

The product is a **chronological timeline per vehicle and per driver**. Three types of records interleave on this timeline:

- **TripLog** — when did the driver take the vehicle, when did they return it, what was the odometer at start and end.
- **DriverReport** — what condition was the vehicle in at handover (good/fair/poor), any notes.
- **IncidentLog** — if something went wrong, what was it, how severe, is it resolved.

The timeline endpoint returns all three sorted by date, creating an unambiguous chain: Driver A took vehicle at 9:00 AM (TripLog), returned it at 2:00 PM noting "vehicle condition: good" (DriverReport). Driver B took it at 2:30 PM (TripLog), returned it at 7:00 PM, reported "front bumper damaged" (DriverReport) and filed an incident (IncidentLog). The damage happened between 2:30 and 7:00 PM — it's Driver B's responsibility.

### How data enters the system

1. `[MANUAL]` **Driver logs a trip.** Start time, end time, start odometer, end odometer, vehicle, notes. Could be entered in real-time (when they start and end) or after the fact. Each log is a "this driver had this vehicle during this window" record.

2. `[COMPUTED]` **Backend computes distance + updates odometer.** `distance_km = end_odometer - start_odometer`. Updates Vehicle.current_odometer if new reading is higher. Same pattern as FuelLog — the odometer stays current through normal workflow usage.

3. `[MANUAL]` **Driver submits a handover report.** At end of shift: vehicle condition (good/fair/poor dropdown), handover notes (free text), issues reported (free text). This is the driver's own record of what state the vehicle was in when they returned it. **Append-only — drivers cannot edit past reports.** This protects the audit trail.

4. `[MANUAL]` **Manager or driver logs an incident.** When something goes wrong: incident type (damage/violation/near_miss), severity (minor/moderate/severe/critical), description, estimated cost. Incidents have a resolution workflow: open → investigating → resolved → closed. Resolution notes are added when closed.

5. `[COMPUTED]` **Timeline endpoint interleaves all records.** GET /vehicles/{id}/timeline does a UNION ALL across trip_logs, driver_reports, and incident_logs for that vehicle, ordered by date descending. Each row carries a "record_type" discriminator so the frontend can render them differently (trip = blue, report = gray, incident = red). Same pattern for GET /drivers/{id}/timeline.

6. `[AI-FUTURE]` **AI scores driver risk and finds patterns.** DriverRisk agent queries IncidentLog + TripLog via MCP. Computes risk scores per driver based on incident frequency and severity. Uses RAG to semantically search incident descriptions for recurring language — "brakes felt soft" across multiple drivers = vehicle issue, not driver issue.

### Models and why each exists

| Model | Why it exists |
|-------|---------------|
| `TripLog` | The "who had the vehicle when" record. Start/end times create the custody window. Odometer readings detect unauthorized use (mileage that doesn't match logged trips). |
| `DriverReport` | The "what condition was it in" record. The vehicle_condition enum (good/fair/poor) creates a measurable handover state. Append-only — no updates allowed. This is the audit evidence. |
| `IncidentLog` | The "something went wrong" record. Severity + resolution workflow lets management track open issues. Description text is vectorized for RAG later. |

### Backend principles applied

**Append-only for accountability records.** DriverReports have no PUT endpoint. Once submitted, they cannot be edited — only new reports can be created. This is a deliberate design choice: if drivers could edit past reports, the audit trail becomes unreliable. IncidentLogs CAN be updated, but only for resolution workflow (status changes, resolution notes) — the original description and severity are immutable after creation.

**Soft-delete everywhere, hard-delete nowhere.** No record in the accountability domain is ever truly deleted. is_deleted=True hides it from normal queries, but it's always recoverable. A fleet manager can't destroy evidence of an incident by deleting it.

**Timeline as a UNION ALL query, not application-layer stitching.** The timeline is a single SQL query that UNIONs three tables with a discriminator column, ordered by date. This is more efficient than three separate queries stitched together in Python, and it guarantees correct chronological ordering even when records from different tables share the same date.

**created_by on every record.** Every audit record tracks who created it. This prevents "I didn't file that report" disputes. The JWT provides the user_id, the service layer stamps it on the record. No one can create a record without being authenticated.

### Routes

| Method | Path | Purpose |
|--------|------|---------|
| POST | `/api/v1/trips` | Log a trip → computes distance, updates odometer |
| GET | `/api/v1/trips` | List trips — filterable by driver, vehicle, date range |
| GET | `/api/v1/trips/{id}` | Get single trip |
| POST | `/api/v1/driver-reports` | Submit handover report — append-only, no updates |
| GET | `/api/v1/driver-reports` | List reports — filterable by driver, vehicle, condition |
| GET | `/api/v1/driver-reports/{id}` | Get single report |
| POST | `/api/v1/incidents` | File an incident |
| GET | `/api/v1/incidents` | List incidents — filterable by type, severity, status |
| GET | `/api/v1/incidents/{id}` | Get single incident |
| PUT | `/api/v1/incidents/{id}` | Update resolution status + notes (not original description) |
| GET | `/api/v1/vehicles/{id}/timeline` | Chronological trips + reports + incidents for one vehicle |
| GET | `/api/v1/drivers/{id}/timeline` | Chronological trips + reports + incidents for one driver |

---

## Problem 5 — Strategic insights

*The data exists across four different domains — nobody sees the full picture.*

### What this problem actually is

The fleet manager knows fuel is expensive (Problem 1). He knows parts run out (Problem 2). He knows trucks break down (Problem 3). He knows about accountability gaps (Problem 4). But he sees each problem in isolation. He can't see that Vehicle #14's fuel costs spiked 30% this month AND a mechanic noted a fuel line issue AND that vehicle is overdue for an inspection AND its driver has had two incidents this quarter. The insight — "Vehicle #14 is a problem asset that needs immediate attention" — exists in the data, but no single view assembles it.

### What the optimized solution is

Two layers working together:

**(a) Backend aggregation endpoints (deterministic)** — pre-built SQL queries that combine data across all domains into dashboard-ready stats. Total fleet cost, vehicle utilization rates, overdue maintenance count, low-stock parts count, open incidents. These are the numbers a fleet manager checks every morning.

**(b) AI executive summaries (intelligent, built later)** — the ExecutiveInsights agent queries these same aggregation endpoints via MCP and generates natural language summaries that connect dots across domains. "Fleet fuel cost up 12% this month, driven by Vehicle #14's abnormal consumption. Mechanic noted possible fuel line issue on Sept 3. Recommend immediate inspection." This is where the entire system's value crystallizes. But the AI can only summarize data that the backend exposes — so the backend must build rich aggregation endpoints first.

### How data enters the system

No new data is entered for this problem. It's purely an output layer — it reads from all the other problems' models and synthesizes. The backend computes deterministic aggregations. The AI module generates natural language analysis. The "input" is the fleet manager asking "how's the fleet doing?"

### Models and why each exists

| Model | Why it exists |
|-------|---------------|
| No new models | This problem reads from Vehicle, FuelLog, MaintenanceLog, PartsInventory, IncidentLog, and ComplianceRule. It creates no new data — it aggregates existing data. |

### Backend principles applied

**Aggregation endpoints are read-only — no writes ever.** These endpoints live under /dashboard/ and use dedicated read-only service functions. They never modify data. They serve two consumers: the frontend (for charts and stats widgets) and the AI module (via MCP tools that mirror these endpoints). Same data, two presentation layers.

**Composite scoring for fleet health.** The fleet-health endpoint computes a per-vehicle health score by combining multiple signals: compliance status (from Problem 3), incident count in the last 90 days (from Problem 4), maintenance currency (from Problem 3), and fuel efficiency trend (from Problem 1). Each signal is normalized to a 0-100 scale and weighted. The composite score is what the AI agent uses to identify "problem vehicles" without examining each domain individually.

**Aggregations built on top of existing service functions.** The /dashboard endpoints don't duplicate query logic — they call existing service functions. fuel_summary calls FuelService.get_monthly_aggregation(). overdue_count calls MaintenanceService.get_overdue_vehicles().count(). This keeps the dashboard layer thin and ensures consistency with the individual domain endpoints.

### Routes

| Method | Path | Purpose |
|--------|------|---------|
| GET | `/api/v1/dashboard/summary` | Fleet snapshot: total vehicles, active drivers, month fuel cost, overdue maintenance count, low-stock parts, open incidents |
| GET | `/api/v1/dashboard/fuel-trends` | Monthly fuel cost for last 12 months — feeds a line chart |
| GET | `/api/v1/dashboard/maintenance-calendar` | Upcoming + overdue services for next 30 days — feeds a calendar view |
| GET | `/api/v1/dashboard/fleet-health` | Per-vehicle composite health score — the AI agent's primary input for executive summaries |

---

## Complete model list (after merge)

16 models total, organized by build dependency. Tier 1 and Tier 2 are defined in full in the Foundation layer above — this table is the condensed reference.

### Tier 1 — Foundation (no domain FKs)

| Model | Key fields |
|-------|------------|
| `Organization` | id (UUID), name, slug (unique), subscription_tier, created_at |
| `User` | id, organization_id (FK), email, hashed_password, full_name, phone (nullable), role (enum: admin/fleet_manager/driver/mechanic), is_active |

### Tier 2 — Core fleet entities

| Model | Key fields |
|-------|------------|
| `Vehicle` | id, org_id, plate_number (unique per org), make, model, year, vin, current_odometer, fuel_type (enum), status (enum: active/maintenance/retired), service_interval_km, service_interval_months |
| `Driver` | id, org_id, user_id (FK, nullable), full_name, license_number, license_expiry, phone, status (enum: active/suspended/inactive) |
| `Supplier` | id, org_id, name, contact_email, phone, avg_lead_time_days, reliability_score (computed) |

### Tier 3 — Domain models

| Model | Key fields | Solves |
|-------|------------|--------|
| `FuelLog` | id, org_id, vehicle_id, driver_id, date, odometer_reading, liters_filled, price_per_liter, total_cost, cost_per_km (computed), notes | Problem 1 |
| `FuelReceipt` | id, fuel_log_id, file_path, file_type, upload_status (enum: pending/parsed/failed), parsed_data (JSONB) | Problem 1 |
| `MaintenanceLog` | id, org_id, vehicle_id, date, odometer_at_service, service_type (enum), description, cost, mechanic_name, next_due_km (computed), next_due_date (computed) | Problem 3 |
| `MechanicReport` | id, maintenance_log_id, diagnostic_notes, findings, actions_taken, parts_used (JSONB), recommendations | Problem 3 + 2 |
| `ComplianceRule` | id, org_id, vehicle_make, vehicle_model, service_type (enum), interval_km, interval_months, description, source_document | Problem 3 |
| `PartsInventory` | id, org_id, supplier_id, part_number, name, category, compatible_vehicles (JSONB), qty_on_hand, reorder_threshold, unit_cost | Problem 2 |
| `PurchaseOrder` | id, org_id, supplier_id, order_date, expected_delivery, actual_delivery, status (enum), total_cost, line_items (JSONB) | Problem 2 |
| `TripLog` | id, org_id, driver_id, vehicle_id, start_time, end_time, start_odometer, end_odometer, distance_km (computed), fuel_consumed, notes | Problem 4 |
| `DriverReport` | id, org_id, driver_id, vehicle_id, shift_date, vehicle_condition (enum: good/fair/poor), handover_notes, issues_reported | Problem 4 |
| `IncidentLog` | id, org_id, driver_id, vehicle_id, incident_type (enum), date, severity (enum), description, location_description, estimated_cost, resolution_status (enum), resolution_notes | Problem 4 |
| `Document` | id, org_id, uploaded_by, document_type (enum), file_path, original_filename, file_size_bytes, mime_type, processing_status (enum), extracted_data (JSONB) | All (file infrastructure) |

### Mixins (inherited by all domain models)

```python
class AuditMixin:
    created_by: UUID  # FK → User
    created_at: datetime  # server_default=now
    updated_by: UUID  # FK → User, nullable
    updated_at: datetime  # onupdate=now
    is_deleted: bool  # default=False
    deleted_at: datetime  # nullable

class OrgScopedMixin:
    organization_id: UUID  # FK → Organization, indexed
```

Every domain model inherits both mixins. All queries filter by `organization_id` and `is_deleted=False`.

---

## Complete route list (after merge)

**48 endpoints** across 12 routers:

### Auth (3 endpoints)
| Method | Path | Purpose |
|--------|------|---------|
| POST | `/api/v1/auth/register` | Create org + admin user |
| POST | `/api/v1/auth/login` | Return JWT |
| GET | `/api/v1/auth/me` | Current user from token |

### Vehicles (7 endpoints)
| Method | Path | Purpose |
|--------|------|---------|
| GET | `/api/v1/vehicles` | List vehicles (paginated, org-scoped) |
| POST | `/api/v1/vehicles` | Create vehicle |
| GET | `/api/v1/vehicles/{id}` | Get vehicle by ID |
| PUT | `/api/v1/vehicles/{id}` | Update vehicle |
| DELETE | `/api/v1/vehicles/{id}` | Soft-delete vehicle |
| GET | `/api/v1/vehicles/{id}/timeline` | Chronological trips + reports + incidents |
| GET | `/api/v1/vehicles/{id}/compliance` | Per-vehicle compliance status |

### Drivers (4 endpoints)
| Method | Path | Purpose |
|--------|------|---------|
| GET | `/api/v1/drivers` | List drivers |
| POST | `/api/v1/drivers` | Create driver |
| GET | `/api/v1/drivers/{id}` | Get driver |
| PUT | `/api/v1/drivers/{id}` | Update driver |
| DELETE | `/api/v1/drivers/{id}` | Soft-delete driver |
| GET | `/api/v1/drivers/{id}/timeline` | Chronological trips + reports + incidents |

### Fuel (6 endpoints — Problem 1)
| Method | Path | Purpose |
|--------|------|---------|
| POST | `/api/v1/fuel` | Create fuel log → computes cost_per_km |
| GET | `/api/v1/fuel` | List fuel logs |
| GET | `/api/v1/fuel/{id}` | Get fuel log |
| PUT | `/api/v1/fuel/{id}` | Update fuel log |
| POST | `/api/v1/fuel/{id}/receipt` | Upload receipt file |
| GET | `/api/v1/fuel/summary` | Monthly aggregation |

### Maintenance (7 endpoints — Problem 3)
| Method | Path | Purpose |
|--------|------|---------|
| POST | `/api/v1/maintenance` | Create log → computes next_due |
| GET | `/api/v1/maintenance` | List logs |
| GET | `/api/v1/maintenance/{id}` | Get log with mechanic report |
| PUT | `/api/v1/maintenance/{id}` | Update log |
| POST | `/api/v1/maintenance/{id}/mechanic-report` | Attach diagnostic report |
| GET | `/api/v1/maintenance/upcoming` | Vehicles near service due |
| GET | `/api/v1/maintenance/overdue` | Vehicles past service deadline |

### Compliance (5 endpoints — Problem 3)
| Method | Path | Purpose |
|--------|------|---------|
| POST | `/api/v1/compliance/rules` | Create manufacturer guideline |
| GET | `/api/v1/compliance/rules` | List rules |
| PUT | `/api/v1/compliance/rules/{id}` | Update rule |
| GET | `/api/v1/compliance/status` | Fleet-wide compliance matrix |
| GET | `/api/v1/compliance/status/{vehicle_id}` | Per-vehicle compliance |

### Inventory (4 endpoints — Problem 2)
| Method | Path | Purpose |
|--------|------|---------|
| POST | `/api/v1/inventory` | Register part |
| GET | `/api/v1/inventory` | List parts |
| PUT | `/api/v1/inventory/{id}` | Update part |
| GET | `/api/v1/inventory/low-stock` | Parts below threshold |

### Suppliers (3 endpoints — Problem 2)
| Method | Path | Purpose |
|--------|------|---------|
| POST | `/api/v1/suppliers` | Register supplier |
| GET | `/api/v1/suppliers` | List suppliers |
| PUT | `/api/v1/suppliers/{id}` | Update supplier |

### Purchase Orders (4 endpoints — Problem 2)
| Method | Path | Purpose |
|--------|------|---------|
| POST | `/api/v1/purchase-orders` | Create order |
| GET | `/api/v1/purchase-orders` | List orders |
| PUT | `/api/v1/purchase-orders/{id}` | Update order |
| PATCH | `/api/v1/purchase-orders/{id}/receive` | Mark received → stock + score update |

### Trips (3 endpoints — Problem 4)
| Method | Path | Purpose |
|--------|------|---------|
| POST | `/api/v1/trips` | Log trip → distance + odometer update |
| GET | `/api/v1/trips` | List trips |
| GET | `/api/v1/trips/{id}` | Get trip |

### Driver Reports (3 endpoints — Problem 4)
| Method | Path | Purpose |
|--------|------|---------|
| POST | `/api/v1/driver-reports` | Submit handover report (append-only) |
| GET | `/api/v1/driver-reports` | List reports |
| GET | `/api/v1/driver-reports/{id}` | Get report |

### Incidents (4 endpoints — Problem 4)
| Method | Path | Purpose |
|--------|------|---------|
| POST | `/api/v1/incidents` | File incident |
| GET | `/api/v1/incidents` | List incidents |
| GET | `/api/v1/incidents/{id}` | Get incident |
| PUT | `/api/v1/incidents/{id}` | Update resolution |

### Dashboard (4 endpoints — Problem 5)
| Method | Path | Purpose |
|--------|------|---------|
| GET | `/api/v1/dashboard/summary` | Fleet overview stats |
| GET | `/api/v1/dashboard/fuel-trends` | 12-month fuel cost trend |
| GET | `/api/v1/dashboard/maintenance-calendar` | 30-day maintenance outlook |
| GET | `/api/v1/dashboard/fleet-health` | Per-vehicle composite health score |

### Documents (3 endpoints — infrastructure)
| Method | Path | Purpose |
|--------|------|---------|
| POST | `/api/v1/documents/upload` | Upload file (multipart) |
| GET | `/api/v1/documents` | List documents |
| GET | `/api/v1/documents/pending` | Unprocessed docs — AI module polls this |
