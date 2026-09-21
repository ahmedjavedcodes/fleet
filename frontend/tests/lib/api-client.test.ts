import { afterEach, describe, expect, it, vi } from "vitest";

import { apiFetch, apiUpload, ApiError } from "@/lib/api-client";

function mockFetchOnce(response: {
  status: number;
  ok: boolean;
  contentType?: string | null;
  body?: unknown;
}) {
  const fetchMock = vi.fn().mockResolvedValue({
    status: response.status,
    ok: response.ok,
    statusText: "",
    headers: { get: (name: string) => (name === "content-type" ? (response.contentType ?? "application/json") : null) },
    json: async () => response.body,
  });
  vi.stubGlobal("fetch", fetchMock);
  return fetchMock;
}

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("apiFetch", () => {
  it("returns the parsed JSON body on success", async () => {
    mockFetchOnce({ status: 200, ok: true, body: { id: "1" } });
    const result = await apiFetch<{ id: string }>("/api/v1/vehicles");
    expect(result).toEqual({ id: "1" });
  });

  it("attaches the Authorization header when a token is given", async () => {
    const fetchMock = mockFetchOnce({ status: 200, ok: true, body: {} });
    await apiFetch("/api/v1/vehicles", { token: "abc123" });
    const [, init] = fetchMock.mock.calls[0];
    expect((init.headers as Record<string, string>).Authorization).toBe("Bearer abc123");
  });

  it("omits the Authorization header when no token is given", async () => {
    const fetchMock = mockFetchOnce({ status: 200, ok: true, body: {} });
    await apiFetch("/api/v1/vehicles");
    const [, init] = fetchMock.mock.calls[0];
    expect((init.headers as Record<string, string>).Authorization).toBeUndefined();
  });

  it("returns undefined for a 204 No Content response without reading the body", async () => {
    const jsonSpy = vi.fn();
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue({
        status: 204,
        ok: true,
        statusText: "",
        headers: { get: () => null },
        json: jsonSpy,
      }),
    );
    const result = await apiFetch("/api/v1/vehicles/1");
    expect(result).toBeUndefined();
    expect(jsonSpy).not.toHaveBeenCalled();
  });

  it.each([
    [401, "unauthorized"],
    [403, "forbidden"],
    [404, "not_found"],
    [409, "conflict"],
    [500, "server"],
  ] as const)("maps HTTP %i to ApiError kind %s", async (status, kind) => {
    mockFetchOnce({ status, ok: false, body: { detail: "boom" } });
    await expect(apiFetch("/api/v1/vehicles")).rejects.toMatchObject({ kind, status, message: "boom" });
  });

  it("extracts field errors from a 422 validation response", async () => {
    mockFetchOnce({
      status: 422,
      ok: false,
      body: {
        detail: [
          { loc: ["body", "email"], msg: "value is not a valid email address", type: "value_error" },
          { loc: ["body", "password"], msg: "field required", type: "missing" },
        ],
      },
    });

    try {
      await apiFetch("/api/v1/auth/login", { method: "POST" });
      expect.unreachable("apiFetch should have thrown");
    } catch (err) {
      expect(err).toBeInstanceOf(ApiError);
      const apiErr = err as ApiError;
      expect(apiErr.kind).toBe("validation");
      expect(apiErr.fieldErrors).toEqual({
        email: "value is not a valid email address",
        password: "field required",
      });
    }
  });

  it("wraps a network failure (fetch throwing) as an ApiError with kind 'network'", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockRejectedValue(new TypeError("Failed to fetch")),
    );
    await expect(apiFetch("/api/v1/vehicles")).rejects.toMatchObject({ kind: "network", status: null });
  });

  it("does not set a Content-Type header when the body is FormData", async () => {
    const fetchMock = mockFetchOnce({ status: 200, ok: true, body: {} });
    const formData = new FormData();
    formData.append("file", new Blob(["x"]), "receipt.jpg");
    await apiUpload("/api/v1/fuel/receipts", formData, "tok");

    const [, init] = fetchMock.mock.calls[0];
    const headers = init.headers as Record<string, string>;
    expect(headers["Content-Type"]).toBeUndefined();
    expect(headers.Authorization).toBe("Bearer tok");
    expect(init.method).toBe("POST");
    expect(init.body).toBe(formData);
  });

  it("sets Content-Type: application/json for a regular JSON request", async () => {
    const fetchMock = mockFetchOnce({ status: 200, ok: true, body: {} });
    await apiFetch("/api/v1/vehicles", { method: "POST", body: JSON.stringify({}) });
    const [, init] = fetchMock.mock.calls[0];
    expect((init.headers as Record<string, string>)["Content-Type"]).toBe("application/json");
  });
});
