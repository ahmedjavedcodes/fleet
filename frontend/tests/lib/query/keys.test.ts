import { describe, expect, it } from "vitest"
import {
  complianceKeys,
  dashboardKeys,
  driverKeys,
  driverReportKeys,
  fuelKeys,
  incidentKeys,
  inventoryKeys,
  maintenanceKeys,
  meKeys,
  purchaseOrderKeys,
  supplierKeys,
  tripKeys,
  vehicleKeys,
} from "@/lib/query/keys"

describe("key hierarchy (every detail/sub-key starts with its domain's .all)", () => {
  it("vehicleKeys", () => {
    expect(vehicleKeys.list()).toEqual(["vehicles", "list"])
    expect(vehicleKeys.detail("v1").slice(0, 1)).toEqual(vehicleKeys.all)
    expect(vehicleKeys.timeline("v1").slice(0, 1)).toEqual(vehicleKeys.all)
    expect(vehicleKeys.compliance("v1").slice(0, 1)).toEqual(vehicleKeys.all)
    expect(vehicleKeys.assignments("v1").slice(0, 1)).toEqual(vehicleKeys.all)
  })

  it("driverKeys, supplierKeys, tripKeys, incidentKeys", () => {
    expect(driverKeys.detail("d1").slice(0, 1)).toEqual(driverKeys.all)
    expect(supplierKeys.list().slice(0, 1)).toEqual(supplierKeys.all)
    expect(tripKeys.detail("t1").slice(0, 1)).toEqual(tripKeys.all)
    expect(incidentKeys.detail("i1").slice(0, 1)).toEqual(incidentKeys.all)
  })

  it("dashboardKeys' sub-resources all start with .all", () => {
    for (const key of [
      dashboardKeys.summary(),
      dashboardKeys.fuelTrends(),
      dashboardKeys.maintenanceCalendar(),
      dashboardKeys.fleetHealth(),
    ]) {
      expect(key.slice(0, 1)).toEqual(dashboardKeys.all)
    }
  })

  it("meKeys.current starts with .all", () => {
    expect(meKeys.current().slice(0, 1)).toEqual(meKeys.all)
  })
})

describe("key stability (same input -> deep-equal key, referentially stable across calls)", () => {
  it("is deterministic for repeated calls with the same arguments", () => {
    expect(vehicleKeys.detail("v1")).toEqual(vehicleKeys.detail("v1"))
    expect(fuelKeys.list({ vehicle_id: "v1" })).toEqual(fuelKeys.list({ vehicle_id: "v1" }))
  })

  it("differs for different filter values (distinct cache entries)", () => {
    expect(fuelKeys.list({ vehicle_id: "v1" })).not.toEqual(fuelKeys.list({ vehicle_id: "v2" }))
    expect(dashboardKeys.fuelTrends(6)).not.toEqual(dashboardKeys.fuelTrends(12))
  })
})

// This is the property that made broad invalidation correct (see keys.ts's
// header comment): TanStack Query's partial-match invalidation only
// prefix-matches a SHORTER filter key against a longer cached key — so
// calling a factory with NO argument must produce an array that is a strict
// prefix of what it produces WITH an argument, never a same-length array
// with an `undefined`-valued filter object (which would silently fail to
// match anything).
function expectPrefix(shorter: readonly unknown[], longer: readonly unknown[]) {
  expect(longer.length).toBeGreaterThan(shorter.length)
  expect(longer.slice(0, shorter.length)).toEqual(shorter)
}

describe("no-argument calls produce a true array prefix of parameterized calls", () => {
  it("fuelKeys.list() / .summary()", () => {
    expectPrefix(fuelKeys.list(), fuelKeys.list({ vehicle_id: "v1" }))
    expectPrefix(fuelKeys.summary(), fuelKeys.summary("2026-01"))
  })

  it("tripKeys.list(), maintenanceKeys.list()/.upcoming(), complianceKeys.rules()", () => {
    expectPrefix(tripKeys.list(), tripKeys.list({ driver_id: "d1" }))
    expectPrefix(maintenanceKeys.list(), maintenanceKeys.list({ vehicle_id: "v1" }))
    expectPrefix(maintenanceKeys.upcoming(), maintenanceKeys.upcoming(1000))
    expectPrefix(complianceKeys.rules(), complianceKeys.rules({ make: "Toyota" }))
  })

  it("inventoryKeys.list(), purchaseOrderKeys.list(), incidentKeys.list(), driverReportKeys.list()", () => {
    expectPrefix(inventoryKeys.list(), inventoryKeys.list({ category: "filters" }))
    expectPrefix(purchaseOrderKeys.list(), purchaseOrderKeys.list({ status: "pending" }))
    expectPrefix(incidentKeys.list(), incidentKeys.list({ severity: "critical" }))
    expectPrefix(driverReportKeys.list(), driverReportKeys.list({ driver_id: "d1" }))
  })

  it("supplierKeys.list(), vehicleKeys.assignments()", () => {
    expectPrefix(supplierKeys.list(), supplierKeys.list("reliability_score"))
    expectPrefix(vehicleKeys.assignments("v1"), vehicleKeys.assignments("v1", "2026-01-01"))
  })

  it("dashboardKeys.fuelTrends() / .maintenanceCalendar()", () => {
    expectPrefix(dashboardKeys.fuelTrends(), dashboardKeys.fuelTrends(12))
    expectPrefix(dashboardKeys.maintenanceCalendar(), dashboardKeys.maintenanceCalendar(30))
  })
})
