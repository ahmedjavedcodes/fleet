import { afterEach, describe, expect, it, vi } from "vitest"
import {
  createChatSession,
  deleteChatSession,
  getChatMessages,
  listChatSessions,
  renameChatSession,
  sendChatMessage,
} from "@/lib/api/chat"

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

function json(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } })
}

async function collect<T>(events: AsyncGenerator<T>): Promise<T[]> {
  const out: T[] = []
  for await (const event of events) out.push(event)
  return out
}

afterEach(() => {
  vi.restoreAllMocks()
})

describe("lib/api/chat createChatSession", () => {
  it("posts to the agents proxy and returns the new session id", async () => {
    const fetchMock = vi.spyOn(globalThis, "fetch").mockResolvedValueOnce(json({ session_id: "s1" }))
    await expect(createChatSession()).resolves.toBe("s1")
    expect(fetchMock).toHaveBeenCalledWith("/api/proxy-agents/chat/sessions", expect.objectContaining({ method: "POST" }))
  })

  it("throws a typed error when the server refuses", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValueOnce(json({ detail: "Missing Bearer token." }, 401))
    await expect(createChatSession()).rejects.toMatchObject({ kind: "unauthorized" })
  })
})

describe("lib/api/chat sendChatMessage", () => {
  it("always targets the session id it is given and streams parsed events", async () => {
    const fetchMock = vi.spyOn(globalThis, "fetch").mockResolvedValueOnce(
      sseResponse([
        'event: activity\ndata: {"agent": "foundation", "step": "Thinking\\u2026", "done": false}\n\n',
        'event: token\ndata: {"text": "Hi"}\n\n',
        'event: done\ndata: {"status": "done"}\n\n',
      ])
    )

    const collected = await collect(sendChatMessage("existing-session", "hello again"))

    expect(collected).toEqual([
      { type: "activity", agent: "foundation", step: "Thinking…", done: false },
      { type: "token", text: "Hi" },
      { type: "done", status: "done" },
    ])
    expect(fetchMock).toHaveBeenCalledTimes(1) // it never creates a session behind the caller's back
    const [url, init] = fetchMock.mock.calls[0]!
    expect(url).toBe("/api/proxy-agents/chat/sessions/existing-session/messages")
    expect(JSON.parse((init as RequestInit).body as string)).toEqual({ message: "hello again" })
  })

  it("sends the referenced documents as document_ids, and nothing extra when there are none", async () => {
    const fetchMock = vi
      .spyOn(globalThis, "fetch")
      .mockResolvedValue(sseResponse(['event: done\ndata: {"status": "done"}\n\n']))
      .mockResolvedValueOnce(sseResponse(['event: done\ndata: {"status": "done"}\n\n']))

    await collect(sendChatMessage("s1", "what does @Manual.pdf say", undefined, "/uploads/incidents/x.jpg", ["doc-1", "doc-2"]))
    await collect(sendChatMessage("s1", "hello", undefined, undefined, []))

    expect(JSON.parse((fetchMock.mock.calls[0]![1] as RequestInit).body as string)).toEqual({
      message: "what does @Manual.pdf say",
      attachment_url: "/uploads/incidents/x.jpg",
      document_ids: ["doc-1", "doc-2"],
    })
    expect(JSON.parse((fetchMock.mock.calls[1]![1] as RequestInit).body as string)).toEqual({ message: "hello" })
  })

  it("silently drops a frame that fails schema validation instead of throwing", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValueOnce(
      sseResponse(['event: token\ndata: {"not_text": "oops"}\n\n', 'event: done\ndata: {"status": "done"}\n\n'])
    )
    expect(await collect(sendChatMessage("s2", "hello"))).toEqual([{ type: "done", status: "done" }])
  })

  it("surfaces a 404 for a session that no longer exists as a typed error", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValueOnce(json({ detail: "Unknown or expired chat session." }, 404))
    await expect(collect(sendChatMessage("gone", "hi"))).rejects.toMatchObject({ kind: "not_found" })
  })
})

const SUMMARY = { id: "s1", title: "Overdue service", message_count: 4, created_at: "2026-09-30T08:00:00Z", updated_at: "2026-09-30T09:00:00Z" }

describe("lib/api/chat session management", () => {
  it("lists the user's sessions from the agents proxy and validates them", async () => {
    const fetchMock = vi.spyOn(globalThis, "fetch").mockResolvedValueOnce(json([SUMMARY]))
    await expect(listChatSessions()).resolves.toEqual([SUMMARY])
    expect(fetchMock.mock.calls[0]![0]).toBe("/api/proxy-agents/chat/sessions")
  })

  it("rejects a session list that does not match the contract", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValueOnce(json([{ id: "s1" }]))
    await expect(listChatSessions()).rejects.toBeDefined()
  })

  it("loads the stored transcript of one session", async () => {
    const rows = [{ id: "m1", role: "user", content: "hi", created_at: "2026-09-30T08:00:00Z" }]
    const fetchMock = vi.spyOn(globalThis, "fetch").mockResolvedValueOnce(json(rows))
    await expect(getChatMessages("s1")).resolves.toEqual(rows)
    expect(fetchMock.mock.calls[0]![0]).toBe("/api/proxy-agents/chat/sessions/s1/messages")
  })

  it("renames with a PATCH carrying only the title", async () => {
    const fetchMock = vi.spyOn(globalThis, "fetch").mockResolvedValueOnce(json({ id: "s1", title: "Fuel review" }))

    await expect(renameChatSession("s1", "Fuel review")).resolves.toEqual({ id: "s1", title: "Fuel review" })

    const [url, init] = fetchMock.mock.calls[0]!
    expect(url).toBe("/api/proxy-agents/chat/sessions/s1")
    expect((init as RequestInit).method).toBe("PATCH")
    expect(JSON.parse((init as RequestInit).body as string)).toEqual({ title: "Fuel review" })
  })

  it("maps a failed rename to a typed error", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValueOnce(json({ detail: "Session not found" }, 404))
    await expect(renameChatSession("nope", "x")).rejects.toMatchObject({ kind: "not_found" })
  })

  it("maps a network failure to a typed error", async () => {
    vi.spyOn(globalThis, "fetch").mockRejectedValueOnce(new TypeError("Failed to fetch"))
    await expect(listChatSessions()).rejects.toMatchObject({ kind: "network" })
  })
})

describe("lib/api/chat deleteChatSession", () => {
  it("sends DELETE through the agents proxy and resolves on 204", async () => {
    const fetchMock = vi.spyOn(globalThis, "fetch").mockResolvedValueOnce(new Response(null, { status: 204 }))
    await expect(deleteChatSession("s1")).resolves.toBeUndefined()
    expect(fetchMock).toHaveBeenCalledWith("/api/proxy-agents/chat/sessions/s1", expect.objectContaining({ method: "DELETE" }))
  })

  it("maps a 404 (unknown or someone else's session) to a not_found ApiError", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValueOnce(json({ detail: "Session not found" }, 404))
    await expect(deleteChatSession("nope")).rejects.toMatchObject({ kind: "not_found" })
  })
})

describe("lib/api/chat sendChatMessage with a photo", () => {
  it("includes attachment_url only when a photo was uploaded", async () => {
    const fetchMock = vi
      .spyOn(globalThis, "fetch")
      .mockImplementation(async () => sseResponse(['event: done\ndata: {"status": "done"}\n\n']))

    await collect(sendChatMessage("s1", "log this", undefined, "/uploads/incidents/a.png"))
    await collect(sendChatMessage("s1", "no photo"))

    const bodies = fetchMock.mock.calls.map(([, init]) => JSON.parse(String((init as RequestInit).body)))
    expect(bodies).toEqual([{ message: "log this", attachment_url: "/uploads/incidents/a.png" }, { message: "no photo" }])
  })
})
