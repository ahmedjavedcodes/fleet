// A minimal `fetch` + `ReadableStream` SSE parser (plans/07 §3) — chosen
// over `EventSource` because the proxy needs custom headers for cookie
// auth that `EventSource` can't send. Not used by any live code path today
// (there's no SSE endpoint to point it at — see lib/api/chat.ts), but kept
// ready and unit-tested against a fake stream for when one exists.

export type ParsedSseEvent = { event?: string; data: string }

/** Parses one `text/event-stream` body into `{event?, data}` frames,
 * splitting on blank-line-terminated blocks per the SSE spec. */
export async function* parseSseStream(body: ReadableStream<Uint8Array>): AsyncGenerator<ParsedSseEvent> {
  const reader = body.getReader()
  const decoder = new TextDecoder()
  let buffer = ""

  try {
    while (true) {
      const { done, value } = await reader.read()
      if (done) break
      buffer += decoder.decode(value, { stream: true })

      let boundary: number
      while ((boundary = buffer.indexOf("\n\n")) !== -1) {
        const block = buffer.slice(0, boundary)
        buffer = buffer.slice(boundary + 2)
        const frame = parseBlock(block)
        if (frame) yield frame
      }
    }
  } finally {
    reader.releaseLock()
  }
}

function parseBlock(block: string): ParsedSseEvent | null {
  let event: string | undefined
  const dataLines: string[] = []
  for (const line of block.split("\n")) {
    if (line.startsWith("event:")) event = line.slice(6).trim()
    else if (line.startsWith("data:")) dataLines.push(line.slice(5).trim())
  }
  if (dataLines.length === 0) return null
  return { event, data: dataLines.join("\n") }
}
