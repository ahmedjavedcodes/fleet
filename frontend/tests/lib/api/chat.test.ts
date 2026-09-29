import { afterEach, describe, expect, it, vi } from "vitest"
import { sendChatMessage } from "@/lib/api/chat"

function sseResponse(frames: string[]): Response {
  const encoder = new TextEncoder()
  const stream = new ReadableStream<Uint8Array>({
    start(controller) {
      for (const frame of frames) controller.enqueue(encoder.encode(frame))
      controller.close()
    },
  })
  return new Response(stream, { status: 200, headers: { "Content-Type": "text/event-stream" } })
}

describe("lib/api/chat sendChatMessage", () => {
  afterEach(() => {
    vi.restoreAllMocks()
  })

  it("creates a session then streams parsed events from the SSE response", async () => {
    const fetchMock = vi
      .spyOn(globalThis, "fetch")
      .mockResolvedValueOnce(new Response(JSON.stringify({ session_id: "s1" }), { status: 200 }))
      .mockResolvedValueOnce(
        sseResponse([
          'event: activity\ndata: {"agent": "foundation", "step": "Thinking\\u2026", "done": false}\n\n',
          'event: token\ndata: {"text": "Hi"}\n\n',
          'event: done\ndata: {"status": "done"}\n\n',
        ])
      )

    const { sessionId, events } = await sendChatMessage("hello")
    expect(sessionId).toBe("s1")

    const collected = []
    for await (const event of events) collected.push(event)

    expect(collected).toEqual([
      { type: "activity", agent: "foundation", step: "Thinking…", done: false },
      { type: "token", text: "Hi" },
      { type: "done", status: "done" },
    ])
    expect(fetchMock).toHaveBeenCalledWith("/api/proxy-agents/chat/sessions", expect.objectContaining({ method: "POST" }))
    expect(fetchMock).toHaveBeenCalledWith("/api/proxy-agents/chat/sessions/s1/messages", expect.objectContaining({ method: "POST" }))
  })

  it("reuses a passed-in sessionId instead of creating a new one", async () => {
    const fetchMock = vi.spyOn(globalThis, "fetch").mockResolvedValueOnce(sseResponse(['event: done\ndata: {"status": "done"}\n\n']))

    const { sessionId, events } = await sendChatMessage("hello again", "existing-session")
    expect(sessionId).toBe("existing-session")
    // streamTurn is an async generator — nothing runs (no fetch) until iterated.
    for await (const _event of events) void _event
    expect(fetchMock).toHaveBeenCalledTimes(1)
    expect(fetchMock).toHaveBeenCalledWith("/api/proxy-agents/chat/sessions/existing-session/messages", expect.anything())
  })

  it("silently drops a frame that fails schema validation instead of throwing", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValueOnce(
      sseResponse(['event: token\ndata: {"not_text": "oops"}\n\n', 'event: done\ndata: {"status": "done"}\n\n'])
    )
    const { events } = await sendChatMessage("hello", "s2")
    const collected = []
    for await (const event of events) collected.push(event)
    expect(collected).toEqual([{ type: "done", status: "done" }])
  })
})
