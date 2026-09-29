import { describe, expect, it } from "vitest"
import { sendMessage } from "@/lib/api/chat"

describe("lib/api/chat", () => {
  it("sendMessage resolves to unavailable regardless of input", async () => {
    await expect(sendMessage({ text: "hello" })).resolves.toEqual({ status: "unavailable" })
    await expect(sendMessage({ text: "ok", approvalResponse: "approve" })).resolves.toEqual({ status: "unavailable" })
  })
})
