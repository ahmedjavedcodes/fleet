import { describe, expect, it } from "vitest"
import { genericErrorMessage, isApiError, networkError, schemaError, toApiError } from "./errors"

describe("toApiError", () => {
  it("maps 401 with no message (never leaks backend detail differences)", () => {
    expect(toApiError(401, { detail: "Invalid credentials" })).toEqual({ kind: "unauthorized", status: 401 })
  })

  it("maps 403 with the backend's message", () => {
    expect(toApiError(403, { detail: "Not enough permissions" })).toEqual({
      kind: "forbidden",
      status: 403,
      message: "Not enough permissions",
    })
  })

  it("maps 404, 409 and 400 with their messages", () => {
    expect(toApiError(404, { detail: "Vehicle not found" })).toEqual({
      kind: "not_found",
      status: 404,
      message: "Vehicle not found",
    })
    expect(toApiError(409, { detail: "Vehicle already assigned" })).toEqual({
      kind: "conflict",
      status: 409,
      message: "Vehicle already assigned",
    })
    expect(toApiError(400, { detail: "Odometer reading must increase" })).toEqual({
      kind: "bad_request",
      status: 400,
      message: "Odometer reading must increase",
    })
  })

  it("maps 413, 415 and 503", () => {
    expect(toApiError(413, undefined)).toEqual({ kind: "payload_too_large", status: 413 })
    expect(toApiError(415, undefined)).toEqual({ kind: "unsupported_media", status: 415 })
    expect(toApiError(503, { detail: "Vector store unavailable" })).toEqual({
      kind: "unavailable",
      status: 503,
      message: "Vector store unavailable",
    })
  })

  it("falls back to a generic 5xx message when there's no detail", () => {
    expect(toApiError(500, undefined)).toEqual({ kind: "server", status: 500 })
    expect(toApiError(502, {})).toEqual({ kind: "server", status: 502 })
  })

  it("builds fieldErrors from a Pydantic 422 detail array, using the last loc segment", () => {
    const body = {
      detail: [
        { type: "value_error", loc: ["body", "odometer_reading"], msg: "must be greater than 0" },
        { type: "missing", loc: ["body", "vehicle_id"], msg: "Field required" },
      ],
    }
    expect(toApiError(422, body)).toEqual({
      kind: "validation",
      status: 422,
      message: "Request failed (422).",
      fieldErrors: {
        odometer_reading: "must be greater than 0",
        vehicle_id: "Field required",
      },
    })
  })

  it("handles a 422 whose detail is a plain string (POST /fuel, driver with no profile)", () => {
    const body = { detail: "Your account isn't linked to a driver profile" }
    expect(toApiError(422, body)).toEqual({
      kind: "validation",
      status: 422,
      message: "Your account isn't linked to a driver profile",
      fieldErrors: {},
    })
  })

  it("reads retryAfter from the Retry-After header on a 429", () => {
    const headers = new Headers({ "Retry-After": "120" })
    expect(toApiError(429, { detail: "Try again shortly" }, headers)).toEqual({
      kind: "rate_limited",
      status: 429,
      message: "Try again shortly",
      retryAfter: 120,
    })
  })

  it("omits retryAfter when the header is absent or non-numeric", () => {
    expect(toApiError(429, undefined)).toMatchObject({ kind: "rate_limited", retryAfter: undefined })
    const headers = new Headers({ "Retry-After": "not-a-number" })
    expect(toApiError(429, undefined, headers)).toMatchObject({ retryAfter: undefined })
  })
})

describe("networkError / schemaError / isApiError", () => {
  it("networkError and schemaError build recognizable ApiErrors", () => {
    expect(isApiError(networkError())).toBe(true)
    expect(isApiError(schemaError("bad shape"))).toBe(true)
    expect(networkError()).toEqual({ kind: "network" })
    expect(schemaError("bad shape")).toEqual({ kind: "schema", issues: "bad shape" })
  })

  it("isApiError rejects plain errors and non-objects", () => {
    expect(isApiError(new Error("boom"))).toBe(false)
    expect(isApiError("boom")).toBe(false)
    expect(isApiError(null)).toBe(false)
    expect(isApiError(undefined)).toBe(false)
  })
})

describe("genericErrorMessage", () => {
  it("gives a fixed message for network, schema, server and unauthorized", () => {
    expect(genericErrorMessage(networkError())).toMatch(/connection/i)
    expect(genericErrorMessage(schemaError("x"))).toMatch(/unexpected/i)
    expect(genericErrorMessage({ kind: "server", status: 500 })).toMatch(/went wrong/i)
    expect(genericErrorMessage({ kind: "unauthorized", status: 401 })).toMatch(/session/i)
  })

  it("falls back to the ApiError's own message otherwise", () => {
    expect(genericErrorMessage({ kind: "not_found", status: 404, message: "Vehicle not found" })).toBe(
      "Vehicle not found"
    )
  })
})
