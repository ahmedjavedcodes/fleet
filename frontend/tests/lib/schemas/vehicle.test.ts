import { describe, expect, it } from "vitest";

import { vehicleCreateSchema } from "@/lib/schemas/vehicle";

const valid = {
  plate_number: "ABC-123",
  make: "Ford",
  model: "Transit",
  year: 2022,
  vin: "1FTBW2CM0NKA12345",
  fuel_type: "diesel" as const,
  status: "active" as const,
  service_interval_km: 10000,
  service_interval_months: 6,
  current_odometer: 5000,
};

describe("vehicleCreateSchema", () => {
  it("accepts a well-formed vehicle payload", () => {
    expect(vehicleCreateSchema.safeParse(valid).success).toBe(true);
  });

  it("rejects a year far in the future", () => {
    const result = vehicleCreateSchema.safeParse({ ...valid, year: new Date().getFullYear() + 5 });
    expect(result.success).toBe(false);
  });

  it("rejects a year that predates the interval floor", () => {
    const result = vehicleCreateSchema.safeParse({ ...valid, year: 1950 });
    expect(result.success).toBe(false);
  });

  it("rejects a fuel_type outside the backend enum", () => {
    const result = vehicleCreateSchema.safeParse({ ...valid, fuel_type: "solar" });
    expect(result.success).toBe(false);
  });

  it("defaults status to 'active' when omitted", () => {
    const { status, ...withoutStatus } = valid;
    void status;
    const result = vehicleCreateSchema.safeParse(withoutStatus);
    expect(result.success).toBe(true);
    if (result.success) expect(result.data.status).toBe("active");
  });

  it("allows null service intervals (vehicle with no configured schedule)", () => {
    const result = vehicleCreateSchema.safeParse({
      ...valid,
      service_interval_km: null,
      service_interval_months: null,
    });
    expect(result.success).toBe(true);
  });

  it("rejects a negative current_odometer", () => {
    const result = vehicleCreateSchema.safeParse({ ...valid, current_odometer: -1 });
    expect(result.success).toBe(false);
  });
});
