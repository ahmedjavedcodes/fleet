import { NextRequest } from "next/server";
import { describe, expect, it } from "vitest";

import { middleware } from "@/middleware";

function makeRequest(pathname: string, { authenticated = false }: { authenticated?: boolean } = {}) {
  const url = `http://localhost:3000${pathname}`;
  const headers = new Headers();
  if (authenticated) headers.set("cookie", "fleet_token=jwt-value");
  return new NextRequest(url, { headers });
}

describe("middleware", () => {
  it("redirects an unauthenticated request to a protected route to /login", () => {
    const response = middleware(makeRequest("/dashboard"));
    expect(response.status).toBe(307);
    const location = new URL(response.headers.get("location")!);
    expect(location.pathname).toBe("/login");
    expect(location.searchParams.get("next")).toBe("/dashboard");
  });

  it("lets an authenticated request through to a protected route", () => {
    const response = middleware(makeRequest("/dashboard", { authenticated: true }));
    expect(response.headers.get("location")).toBeNull();
  });

  it("lets an unauthenticated request through to /login", () => {
    const response = middleware(makeRequest("/login"));
    expect(response.headers.get("location")).toBeNull();
  });

  it("redirects an already-authenticated request away from /login to /dashboard", () => {
    const response = middleware(makeRequest("/login", { authenticated: true }));
    expect(response.status).toBe(307);
    const location = new URL(response.headers.get("location")!);
    expect(location.pathname).toBe("/dashboard");
  });
});
