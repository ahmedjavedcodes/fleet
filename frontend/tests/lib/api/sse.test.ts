import { describe, expect, it } from "vitest"
import { parseSseStream } from "@/lib/api/sse"

function streamFrom(chunks: string[]): ReadableStream<Uint8Array> {
  const encoder = new TextEncoder()
  let i = 0
  return new ReadableStream({
    pull(controller) {
      if (i < chunks.length) {
        controller.enqueue(encoder.encode(chunks[i]))
        i++
      } else {
        controller.close()
      }
    },
  })
}

describe("parseSseStream", () => {
  it("parses event+data frames split across multiple chunk boundaries", async () => {
    const stream = streamFrom(["event: token\ndata: hel", "lo\n\nevent: done\ndata: {}\n\n"])
    const frames = []
    for await (const frame of parseSseStream(stream)) frames.push(frame)
    expect(frames).toEqual([
      { event: "token", data: "hello" },
      { event: "done", data: "{}" },
    ])
  })

  it("joins multi-line data fields with newlines", async () => {
    const stream = streamFrom(["event: token\ndata: line1\ndata: line2\n\n"])
    const frames = []
    for await (const frame of parseSseStream(stream)) frames.push(frame)
    expect(frames).toEqual([{ event: "token", data: "line1\nline2" }])
  })

  it("skips a block with no data line", async () => {
    const stream = streamFrom([": keepalive comment\n\nevent: done\ndata: ok\n\n"])
    const frames = []
    for await (const frame of parseSseStream(stream)) frames.push(frame)
    expect(frames).toEqual([{ event: "done", data: "ok" }])
  })

  // Regression: sse-starlette (ai_agents/server.py) sends CRLF line endings,
  // not LF — a real production bug where the LF-only boundary check above
  // buffered every frame forever and never yielded anything, silently, all
  // the way to stream close. Caught live in the browser, not by the LF-only
  // tests above.
  it("parses CRLF-terminated frames (sse-starlette's actual wire format)", async () => {
    const stream = streamFrom(['event: activity\r\ndata: {"agent": "foundation"}\r\n\r\n', 'event: token\r\ndata: {"text": "Hi"}\r\n\r\n'])
    const frames = []
    for await (const frame of parseSseStream(stream)) frames.push(frame)
    expect(frames).toEqual([
      { event: "activity", data: '{"agent": "foundation"}' },
      { event: "token", data: '{"text": "Hi"}' },
    ])
  })

  it("parses a CRLF frame split across chunk boundaries mid-terminator", async () => {
    const stream = streamFrom(["event: token\r\ndata: hi\r", "\ndata: there\r\n\r\n"])
    const frames = []
    for await (const frame of parseSseStream(stream)) frames.push(frame)
    expect(frames).toEqual([{ event: "token", data: "hi\nthere" }])
  })
})
