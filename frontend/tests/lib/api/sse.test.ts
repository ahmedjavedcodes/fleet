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
})
