import { describe, expect, it } from "vitest";

import { loginSchema, registerSchema } from "@/lib/schemas/auth";

describe("loginSchema", () => {
  const valid = { org_slug: "acme-logistics", email: "admin@acme.com", password: "hunter2" };

  it("accepts a well-formed login payload", () => {
    expect(loginSchema.safeParse(valid).success).toBe(true);
  });

  it("rejects an uppercase or invalid org_slug", () => {
    const result = loginSchema.safeParse({ ...valid, org_slug: "Acme_Logistics" });
    expect(result.success).toBe(false);
  });

  it("rejects a malformed email", () => {
    const result = loginSchema.safeParse({ ...valid, email: "not-an-email" });
    expect(result.success).toBe(false);
  });

  it("rejects an empty password", () => {
    const result = loginSchema.safeParse({ ...valid, password: "" });
    expect(result.success).toBe(false);
  });
});

describe("registerSchema", () => {
  const valid = {
    organization_name: "Acme Logistics",
    organization_slug: "acme-logistics",
    admin_email: "admin@acme.com",
    admin_password: "supersecret",
    admin_full_name: "Jane Admin",
  };

  it("accepts a well-formed registration payload", () => {
    expect(registerSchema.safeParse(valid).success).toBe(true);
  });

  it("rejects a password shorter than 8 characters", () => {
    const result = registerSchema.safeParse({ ...valid, admin_password: "short" });
    expect(result.success).toBe(false);
  });

  it("rejects a slug with spaces or uppercase letters", () => {
    const result = registerSchema.safeParse({ ...valid, organization_slug: "Acme Logistics" });
    expect(result.success).toBe(false);
  });
});
