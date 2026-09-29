import { z } from "zod"
import { networkError, schemaError, toApiError } from "./errors"
import { parseSseStream } from "./sse"
import { chatEventSchema, type ChatEvent } from "@/lib/schemas/chat"

// The ai_agents chat server (server.py), proxied through /api/proxy-agents
// so the session cookie's Bearer token is attached server-side, same as
// lib/api/client.ts does for the main backend. This is a real, live
// integration — ai_agents/orchestrator's Grand Orchestrator actually runs,
// calling real backend endpoints, not a mock.

async function createSession(): Promise<string> {
  let response: Response
  try {
    response = await fetch("/api/proxy-agents/chat/sessions", { method: "POST", credentials: "same-origin" })
  } catch {
    throw networkError()
  }
  if (!response.ok) {
    const body = await response.json().catch(() => undefined)
    throw toApiError(response.status, body, response.headers)
  }
  const json = await response.json()
  const result = z.object({ session_id: z.string() }).safeParse(json)
  if (!result.success) throw schemaError(result.error.message)
  return result.data.session_id
}

async function* streamTurn(path: string, body?: unknown, signal?: AbortSignal): AsyncGenerator<ChatEvent> {
  let response: Response
  try {
    response = await fetch(`/api/proxy-agents${path}`, {
      method: "POST",
      headers: { Accept: "text/event-stream", ...(body !== undefined ? { "Content-Type": "application/json" } : {}) },
      body: body !== undefined ? JSON.stringify(body) : undefined,
      credentials: "same-origin",
      signal,
    })
  } catch (err) {
    if (err instanceof DOMException && err.name === "AbortError") return
    throw networkError()
  }
  if (!response.ok || !response.body) {
    const errBody = await response.json().catch(() => undefined)
    throw toApiError(response.status, errBody, response.headers)
  }

  try {
    for await (const frame of parseSseStream(response.body)) {
      if (!frame.event) continue
      let parsedData: unknown
      try {
        parsedData = JSON.parse(frame.data)
      } catch {
        continue
      }
      const result = chatEventSchema.safeParse({ type: frame.event, ...(parsedData as object) })
      if (!result.success) {
        console.error(`Schema validation failed for chat event ${frame.event}:`, result.error)
        continue
      }
      yield result.data
    }
  } catch (err) {
    if (err instanceof DOMException && err.name === "AbortError") return
    throw err
  }
}

/** Creates a session (if `sessionId` is omitted) and streams the response to
 * a user message. Returns the session id alongside the event stream so the
 * caller can persist it for the next turn. */
export async function sendChatMessage(
  message: string,
  sessionId?: string,
  signal?: AbortSignal
): Promise<{ sessionId: string; events: AsyncGenerator<ChatEvent> }> {
  const id = sessionId ?? (await createSession())
  return { sessionId: id, events: streamTurn(`/chat/sessions/${id}/messages`, { message }, signal) }
}

export function approveChatAction(sessionId: string, signal?: AbortSignal): AsyncGenerator<ChatEvent> {
  return streamTurn(`/chat/sessions/${sessionId}/approve`, undefined, signal)
}

export function modifyChatAction(sessionId: string, updates: Record<string, unknown>, signal?: AbortSignal): AsyncGenerator<ChatEvent> {
  return streamTurn(`/chat/sessions/${sessionId}/modify`, { updates }, signal)
}

export function rejectChatAction(sessionId: string, signal?: AbortSignal): AsyncGenerator<ChatEvent> {
  return streamTurn(`/chat/sessions/${sessionId}/reject`, undefined, signal)
}

export type { ChatEvent }
