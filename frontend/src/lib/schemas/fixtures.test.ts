import { describe, expect, it } from "vitest"
import { meResponseSchema } from "./auth"
import { driverAssignmentHistoryResponseSchema } from "./assignment"
import { complianceRuleCreateSchema, vehicleComplianceResponseSchema } from "./compliance"
import { dashboardSummaryResponseSchema, fleetHealthResponseSchema } from "./dashboard"
import { driverSchema } from "./driver"
import { driverReportSchema } from "./driver-report"
import { fuelLogSchema, fuelLogCreateSchema, fuelSummaryResponseSchema } from "./fuel"
import { incidentLogSchema, incidentLogCreateSchema } from "./incident"
import { partsInventoryCreateSchema, lowStockResponseSchema } from "./inventory"
import { maintenanceLogSchema, maintenanceLogCreateSchema } from "./maintenance"
import { purchaseOrderReceiveResponseSchema } from "./purchase-order"
import { supplierSchema } from "./supplier"
import { timelineResponseSchema } from "./timeline"
import { tripLogSchema, tripLogCreateSchema } from "./trip"
import { vehicleSchema, vehicleCreateSchema } from "./vehicle"

// Fixtures for /auth/me and GET /vehicles are the *actual* JSON captured
// live from the seeded dev backend during phase-02 verification (plans/02
// exit criteria). The rest are built directly from the Pydantic field
// definitions in backend/app/schemas/*.py, since standing up every domain's
// data (fuel logs, incidents, assignments, …) in a fresh dev DB wasn't
// practical here — re-verify against a live capture as each module is
// built (CLAUDE.md §8).

describe("auth schemas", () => {
  it("parses a real GET /auth/me response", () => {
    const fixture = {
      user: {
        id: "934a4f82-a415-4327-a4a1-0d5fffbb00a9",
        organization_id: "a01ee75d-3ff9-4704-ac91-eea92f475488",
        email: "admin@fleet-registry-agent-test.dev",
        full_name: "Test Admin",
        phone: null,
        role: "admin",
        is_active: true,
        last_login_at: "2026-09-28T15:39:12.638714+05:00",
      },
      organization: {
        id: "a01ee75d-3ff9-4704-ac91-eea92f475488",
        name: "Fleet Registry Agent Test Org",
        slug: "fleet-registry-agent-test",
        subscription_tier: "trial",
        created_at: "2026-09-21T19:08:06.472010+05:00",
      },
      driver_profile: null,
    }
    expect(meResponseSchema.parse(fixture)).toEqual(fixture)
  })
})

describe("vehicle schemas", () => {
  it("parses a real GET /vehicles entry", () => {
    const fixture = {
      plate_number: "XYZ-789",
      make: "Toyota",
      model: "Hilux",
      year: 2021,
      vin: "JT111HILUX000123",
      fuel_type: "diesel",
      status: "active",
      service_interval_km: null,
      service_interval_months: null,
      id: "d820c40f-c9ab-470e-95cc-b4adf8e1503e",
      organization_id: "a01ee75d-3ff9-4704-ac91-eea92f475488",
      current_odometer: 0,
    }
    expect(vehicleSchema.parse(fixture)).toEqual(fixture)
  })

  it("rejects a create payload with an unknown field (extra_forbidden mirror)", () => {
    const result = vehicleCreateSchema.safeParse({
      plate_number: "ABC-1",
      make: "Toyota",
      model: "Hilux",
      year: 2021,
      vin: "VIN1",
      fuel_type: "diesel",
      not_a_real_field: true,
    })
    expect(result.success).toBe(false)
  })
})

describe("driver / supplier schemas", () => {
  it("parses a DriverResponse", () => {
    expect(
      driverSchema.parse({
        id: "22222222-2222-4222-8222-222222222222",
        organization_id: "33333333-3333-4333-8333-333333333333",
        user_id: null,
        full_name: "Test Driver",
        license_number: "LIC-1",
        license_expiry: "2027-01-01",
        phone: "+92 300 0000000",
        status: "active",
      })
    ).toBeTruthy()
  })

  it("parses a SupplierResponse with a decimal-string reliability_score", () => {
    expect(
      supplierSchema.parse({
        id: "44444444-4444-4444-8444-444444444444",
        organization_id: "33333333-3333-4333-8333-333333333333",
        name: "Acme Parts",
        contact_email: "sales@acme.example",
        phone: null,
        avg_lead_time_days: 5,
        reliability_score: "0.8500",
      })
    ).toBeTruthy()
  })
})

describe("fuel schemas", () => {
  it("parses a FuelLogResponse, including a null cost_per_km on a first log", () => {
    expect(
      fuelLogSchema.parse({
        id: "dddddddd-dddd-4ddd-8ddd-dddddddddddd",
        vehicle_id: "11111111-1111-4111-8111-111111111111",
        driver_id: "22222222-2222-4222-8222-222222222222",
        date: "2026-06-12",
        odometer_reading: 12000,
        liters_filled: "45.5000",
        price_per_liter: "280.0000",
        total_cost: "12740.0000",
        cost_per_km: null,
        is_anomalous: false,
        notes: null,
        created_at: "2026-06-12T09:00:00Z",
      })
    ).toBeTruthy()
  })

  it("rejects a FuelLogCreate with extra fields (extra_forbidden)", () => {
    const result = fuelLogCreateSchema.safeParse({
      vehicle_id: "11111111-1111-4111-8111-111111111111",
      date: "2026-06-12",
      odometer_reading: 12000,
      liters_filled: 45.5,
      price_per_liter: 280,
      total_cost: 12740,
      unexpected: "nope",
    })
    expect(result.success).toBe(false)
  })

  it("parses a FuelSummaryResponse with a per-vehicle breakdown", () => {
    expect(
      fuelSummaryResponseSchema.parse({
        month: "2026-06",
        total_cost: "50000.0000",
        total_liters: "180.0000",
        avg_cost_per_km: "27.5000",
        by_vehicle: [{ vehicle_id: "11111111-1111-4111-8111-111111111111", total_cost: "50000.0000", total_liters: "180.0000", avg_cost_per_km: "27.5000" }],
      })
    ).toBeTruthy()
  })
})

describe("trip / driver-report / incident schemas", () => {
  it("parses a TripLogResponse", () => {
    expect(
      tripLogSchema.parse({
        id: "99999999-9999-4999-8999-999999999999",
        driver_id: "22222222-2222-4222-8222-222222222222",
        vehicle_id: "11111111-1111-4111-8111-111111111111",
        start_time: "2026-06-12T08:00:00Z",
        end_time: "2026-06-12T10:15:00Z",
        start_odometer: 12000,
        end_odometer: 12098,
        distance_km: 98,
        fuel_consumed: "11.2000",
        notes: null,
        created_at: "2026-06-12T10:16:00Z",
      })
    ).toBeTruthy()
  })

  it("rejects a TripLogCreate missing end_time (both ends are required)", () => {
    const result = tripLogCreateSchema.safeParse({
      driver_id: "22222222-2222-4222-8222-222222222222",
      vehicle_id: "11111111-1111-4111-8111-111111111111",
      start_time: "2026-06-12T08:00:00Z",
      start_odometer: 12000,
      end_odometer: 12098,
    })
    expect(result.success).toBe(false)
  })

  it("parses a DriverReportResponse", () => {
    expect(
      driverReportSchema.parse({
        id: "77777777-7777-4777-8777-777777777777",
        driver_id: "22222222-2222-4222-8222-222222222222",
        vehicle_id: "11111111-1111-4111-8111-111111111111",
        shift_date: "2026-06-12",
        vehicle_condition: "good",
        handover_notes: null,
        issues_reported: null,
        created_at: "2026-06-12T18:00:00Z",
      })
    ).toBeTruthy()
  })

  it("parses an IncidentLogResponse and rejects an IncidentLogCreate with an invalid severity", () => {
    expect(
      incidentLogSchema.parse({
        id: "88888888-8888-4888-8888-888888888888",
        driver_id: "22222222-2222-4222-8222-222222222222",
        vehicle_id: "11111111-1111-4111-8111-111111111111",
        incident_type: "near_miss",
        date: "2026-06-12",
        severity: "moderate",
        description: "Hard brake avoiding a pedestrian",
        location_description: null,
        estimated_cost: null,
        resolution_status: "open",
        resolution_notes: null,
        created_at: "2026-06-12T18:00:00Z",
      })
    ).toBeTruthy()

    const result = incidentLogCreateSchema.safeParse({
      vehicle_id: "11111111-1111-4111-8111-111111111111",
      incident_type: "near_miss",
      date: "2026-06-12",
      severity: "catastrophic",
      description: "x",
    })
    expect(result.success).toBe(false)
  })
})

describe("maintenance / inventory / compliance schemas", () => {
  it("parses a MaintenanceLogResponse with a nested mechanic report", () => {
    expect(
      maintenanceLogSchema.parse({
        id: "cccccccc-cccc-4ccc-8ccc-cccccccccccc",
        vehicle_id: "11111111-1111-4111-8111-111111111111",
        date: "2026-06-01",
        odometer_at_service: 11000,
        service_type: "oil_change",
        description: "Routine oil change",
        cost: "3500.0000",
        mechanic_name: "Ali",
        next_due_km: 21000,
        next_due_date: "2026-12-01",
        created_at: "2026-06-01T12:00:00Z",
        mechanic_report: {
          id: "66666666-6666-4666-8666-666666666666",
          maintenance_log_id: "cccccccc-cccc-4ccc-8ccc-cccccccccccc",
          diagnostic_notes: "All good",
          findings: null,
          actions_taken: "Changed oil and filter",
          parts_used: [{ part_id: "55555555-5555-4555-8555-555555555555", qty: 1 }],
          recommendations: null,
          low_stock_alerts: [],
        },
      })
    ).toBeTruthy()
  })

  it("rejects a MaintenanceLogCreate with an unknown field", () => {
    const result = maintenanceLogCreateSchema.safeParse({
      vehicle_id: "11111111-1111-4111-8111-111111111111",
      date: "2026-06-01",
      odometer_at_service: 11000,
      service_type: "oil_change",
      bogus: true,
    })
    expect(result.success).toBe(false)
  })

  it("parses a LowStockResponse (adds deficit to PartsInventoryResponse)", () => {
    expect(
      lowStockResponseSchema.parse({
        id: "55555555-5555-4555-8555-555555555555",
        organization_id: "33333333-3333-4333-8333-333333333333",
        part_number: "OIL-5W30",
        name: "Engine oil 5W-30",
        category: "fluids",
        compatible_vehicles: [{ make: "Toyota", model: "Hilux" }],
        reorder_threshold: 10,
        unit_cost: "1200.0000",
        supplier_id: "44444444-4444-4444-8444-444444444444",
        qty_on_hand: 3,
        deficit: 7,
      })
    ).toBeTruthy()
  })

  it("rejects a PartsInventoryCreate with an unknown field", () => {
    const result = partsInventoryCreateSchema.safeParse({
      part_number: "OIL-5W30",
      name: "Engine oil 5W-30",
      reorder_threshold: 10,
      unit_cost: 1200,
      typo_field: 1,
    })
    expect(result.success).toBe(false)
  })

  it("rejects a ComplianceRuleCreate missing a required field", () => {
    const result = complianceRuleCreateSchema.safeParse({
      vehicle_make: "Toyota",
      vehicle_model: "Hilux",
      service_type: "oil_change",
      interval_km: 10000,
      // interval_months missing
    })
    expect(result.success).toBe(false)
  })

  it("parses a VehicleComplianceResponse with every compliance status literal", () => {
    for (const status of ["compliant", "due_soon", "overdue", "never_performed"] as const) {
      expect(
        vehicleComplianceResponseSchema.parse({
          vehicle_id: "11111111-1111-4111-8111-111111111111",
          items: [
            {
              rule: {
                id: "77777777-7777-4777-8777-777777777777",
                organization_id: "33333333-3333-4333-8333-333333333333",
                vehicle_make: "Toyota",
                vehicle_model: "Hilux",
                service_type: "oil_change",
                interval_km: 10000,
                interval_months: 6,
                description: null,
                source_document: null,
              },
              status,
              km_remaining: status === "overdue" ? -500 : 500,
              days_remaining: 30,
              last_service_date: "2026-01-01",
            },
          ],
        })
      ).toBeTruthy()
    }
  })
})

describe("purchase order / assignment / timeline / dashboard schemas", () => {
  it("parses a PurchaseOrderReceiveResponse", () => {
    expect(
      purchaseOrderReceiveResponseSchema.parse({
        order: {
          id: "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb",
          organization_id: "33333333-3333-4333-8333-333333333333",
          supplier_id: "44444444-4444-4444-8444-444444444444",
          order_date: "2026-06-01",
          expected_delivery: "2026-06-10",
          actual_delivery: "2026-06-09",
          status: "received",
          total_cost: "24000.0000",
          line_items: [{ part_id: "55555555-5555-4555-8555-555555555555", qty: 20, unit_price: "1200.0000" }],
        },
        stock_updates: [{ part_id: "55555555-5555-4555-8555-555555555555", new_qty: 23 }],
      })
    ).toBeTruthy()
  })

  it("parses a DriverAssignmentHistoryResponse, with duration_hours null while active", () => {
    expect(
      driverAssignmentHistoryResponseSchema.parse({
        driver_id: "22222222-2222-4222-8222-222222222222",
        current_assignment: {
          id: "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa",
          vehicle_id: "11111111-1111-4111-8111-111111111111",
          driver_id: "22222222-2222-4222-8222-222222222222",
          assigned_at: "2026-06-01T08:00:00Z",
          released_at: null,
          start_odometer: 10000,
          end_odometer: null,
          take_condition: "good",
          leave_condition: null,
          take_notes: null,
          leave_notes: null,
          created_at: "2026-06-01T08:00:00Z",
          duration_hours: null,
        },
        total_vehicles_driven: 2,
        history: [],
      })
    ).toBeTruthy()
  })

  it("parses a TimelineResponse discriminated on record_type", () => {
    const fixture = [
      {
        record_type: "trip",
        id: "99999999-9999-4999-8999-999999999999",
        date: "2026-06-12T08:00:00Z",
        summary: {
          driver_id: "22222222-2222-4222-8222-222222222222",
          vehicle_id: "11111111-1111-4111-8111-111111111111",
          start_time: "2026-06-12T08:00:00Z",
          end_time: "2026-06-12T10:00:00Z",
          start_odometer: 100,
          end_odometer: 198,
          distance_km: 98,
          fuel_consumed: null,
          notes: null,
        },
      },
      {
        record_type: "incident",
        id: "88888888-8888-4888-8888-888888888888",
        date: "2026-06-13T08:00:00Z",
        summary: {
          driver_id: null,
          vehicle_id: "11111111-1111-4111-8111-111111111111",
          incident_type: "damage",
          date: "2026-06-13",
          severity: "minor",
          description: "Scratch on bumper",
          location_description: null,
          estimated_cost: null,
          resolution_status: "open",
          resolution_notes: null,
        },
      },
    ]
    expect(timelineResponseSchema.parse(fixture)).toHaveLength(2)
  })

  it("parses a DashboardSummaryResponse and a FleetHealthResponse with null signals", () => {
    expect(
      dashboardSummaryResponseSchema.parse({
        total_vehicles: 12,
        active_drivers: 8,
        month_fuel_cost: "120000.0000",
        overdue_maintenance_count: 2,
        low_stock_parts_count: 1,
        open_incidents_count: 0,
      })
    ).toBeTruthy()

    expect(
      fleetHealthResponseSchema.parse([
        {
          vehicle_id: "11111111-1111-4111-8111-111111111111",
          plate_number: "XYZ-789",
          health_score: 76,
          signals: { compliance: 90, incidents: null, maintenance_currency: 60, fuel_efficiency: null },
        },
      ])
    ).toBeTruthy()
  })
})
