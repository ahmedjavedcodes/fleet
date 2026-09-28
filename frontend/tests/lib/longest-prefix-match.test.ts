import { describe, expect, it } from "vitest"
import { longestPrefixMatch } from "@/lib/longest-prefix-match"

const entries = [
  { prefix: "/foundation", value: "loose" },
  { prefix: "/foundation/vehicles", value: "specific" },
]

describe("longestPrefixMatch", () => {
  it("prefers the more specific (longer) prefix", () => {
    expect(longestPrefixMatch(entries, "/foundation/vehicles")?.value).toBe("specific")
    expect(longestPrefixMatch(entries, "/foundation/vehicles/abc")?.value).toBe("specific")
  })

  it("falls back to the looser prefix outside the specific one", () => {
    expect(longestPrefixMatch(entries, "/foundation")?.value).toBe("loose")
    expect(longestPrefixMatch(entries, "/foundation/drivers")?.value).toBe("loose")
  })

  it("requires a path-segment boundary, not just a string prefix", () => {
    // "/foundationX" must not match "/foundation".
    expect(longestPrefixMatch(entries, "/foundationX")).toBeUndefined()
  })

  it("returns undefined when nothing matches", () => {
    expect(longestPrefixMatch(entries, "/unrelated")).toBeUndefined()
  })
})
