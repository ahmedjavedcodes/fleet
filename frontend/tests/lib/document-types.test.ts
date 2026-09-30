import { describe, expect, it } from "vitest"
import { isPdf, uploadableDocumentTypes } from "@/lib/document-types"

describe("uploadableDocumentTypes", () => {
  it("lets admins upload every type, fleet managers all but legal, and nobody else any", () => {
    expect(uploadableDocumentTypes("admin")).toEqual(["manual", "policy", "supplier_invoice", "incident_report", "legal"])
    expect(uploadableDocumentTypes("fleet_manager")).toEqual(["manual", "policy", "supplier_invoice", "incident_report"])
    for (const role of ["driver", "mechanic", null, undefined, ""]) expect(uploadableDocumentTypes(role)).toEqual([])
  })
})

describe("isPdf", () => {
  it("recognises a PDF by MIME type, or by extension when the browser gives no type", () => {
    expect(isPdf(new File(["x"], "a.pdf", { type: "application/pdf" }))).toBe(true)
    expect(isPdf(new File(["x"], "A.PDF", { type: "" }))).toBe(true)
    expect(isPdf(new File(["x"], "a.png", { type: "image/png" }))).toBe(false)
    expect(isPdf(new File(["x"], "a.pdf", { type: "image/png" }))).toBe(false)
  })
})
