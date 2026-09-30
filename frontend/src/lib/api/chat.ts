import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { z } from "zod"
import { chatKeys } from "@/lib/query/keys"
import { networkError, schemaError, toApiError } from "./errors"
import { parseSseStream } from "./sse"
import {
  chatEventSchema,
  chatSessionSummarySchema,
  renamedChatSessionSchema,
  storedChatMessageSchema,
  type ChatEvent,
  type ChatSessionSummary,
  type RenamedChatSession,
  type StoredChatMessage,
} from "@/lib/schemas/chat"

// The ai_agents chat server (server.py), proxied through /api/proxy-agents
// so the session cookie's Bearer token is attached server-side, same as
// lib/api/client.ts does for the main backend. This is a real, live
// integration — ai_agents/orchestrator's Grand Orchestrator actually runs,
// calling real backend endpoints, not a mock.
//
// A chat session's id is the id of its persisted memory session, so the same id
// lists it in the sidebar, reopens its transcript, and continues the thread.

const AGENTS = "/api/proxy-agents"

async function agentsRequest<T>(path: string, options: { method?: "GET" | "PATCH"; body?: unknown; schema: z.ZodType<T> }): Promise<T> {
  const { method = "GET", body, schema } = options
  let response: Response
  try {
    response = await fetch(`${AGENTS}${path}`, {
      method,
      headers: { Accept: "application/json", ...(body !== undefined ? { "Content-Type": "application/json" } : {}) },
      body: body !== undefined ? JSON.stringify(body) : undefined,
      credentials: "same-origin",
    })
  } catch {
    throw networkError()
  }
  if (!response.ok) {
    const errorBody = await response.json().catch(() => undefined)
    throw toApiError(response.status, errorBody, response.headers)
  }
  const parsed = schema.safeParse(await response.json().catch(() => undefined))
  if (!parsed.success) throw schemaError(parsed.error.message)
  return parsed.data
}

// --- Sessions -----------------------------------------------------------

/** Starts a new, empty conversation and returns its id. */
export async function createChatSession(): Promise<string> {
  let response: Response
  try {
    response = await fetch(`${AGENTS}/chat/sessions`, { method: "POST", credentials: "same-origin" })
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

/** The signed-in user's own conversations, most recently active first. */
export function listChatSessions(): Promise<ChatSessionSummary[]> {
  return agentsRequest("/chat/sessions", { schema: z.array(chatSessionSummarySchema) })
}

/** The stored transcript of one conversation. */
export function getChatMessages(sessionId: string): Promise<StoredChatMessage[]> {
  return agentsRequest(`/chat/sessions/${sessionId}/messages`, { schema: z.array(storedChatMessageSchema) })
}

export function renameChatSession(sessionId: string, title: string): Promise<RenamedChatSession> {
  return agentsRequest(`/chat/sessions/${sessionId}`, { method: "PATCH", body: { title }, schema: renamedChatSessionSchema })
}

/** Permanently deletes one of the caller's conversations and its transcript. */
export async function deleteChatSession(sessionId: string): Promise<void> {
  let response: Response
  try {
    response = await fetch(`${AGENTS}/chat/sessions/${sessionId}`, { method: "DELETE", credentials: "same-origin" })
  } catch {
    throw networkError()
  }
  if (!response.ok) {
    const body = await response.json().catch(() => undefined)
    throw toApiError(response.status, body, response.headers)
  }
}

export function useDeleteChatSession() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: deleteChatSession,
    onSuccess: (_result, id) => {
      queryClient.setQueryData<ChatSessionSummary[]>(chatKeys.sessions(), (rows) => rows?.filter((s) => s.id !== id))
    },
    onSettled: () => queryClient.invalidateQueries({ queryKey: chatKeys.sessions() }),
  })
}

export function useChatSessions() {
  return useQuery({ queryKey: chatKeys.sessions(), queryFn: listChatSessions })
}

/** The transcript of the opened conversation. `enabled` is false when the page already holds
 * this conversation live, so a turn in progress is never overwritten by a stale copy. */
export function useChatMessages(sessionId: string | null, enabled: boolean) {
  return useQuery({
    queryKey: chatKeys.messages(sessionId ?? "none"),
    queryFn: () => getChatMessages(sessionId as string),
    enabled: enabled && Boolean(sessionId),
    // A transcript is only re-read when a conversation is opened; live turns append locally.
    staleTime: 0,
    gcTime: 0,
  })
}

export function useRenameChatSession() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: ({ id, title }: { id: string; title: string }) => renameChatSession(id, title),
    // Show the new title at once; the refetch on settle confirms it, or restores the old one on failure.
    onMutate: async ({ id, title }) => {
      await queryClient.cancelQueries({ queryKey: chatKeys.sessions() })
      const previous = queryClient.getQueryData<ChatSessionSummary[]>(chatKeys.sessions())
      queryClient.setQueryData<ChatSessionSummary[]>(chatKeys.sessions(), (rows) =>
        rows?.map((s) => (s.id === id ? { ...s, title } : s))
      )
      return { previous }
    },
    onError: (_error, _vars, context) => {
      if (context?.previous) queryClient.setQueryData(chatKeys.sessions(), context.previous)
    },
    onSettled: () => queryClient.invalidateQueries({ queryKey: chatKeys.sessions() }),
  })
}

// --- Turns (SSE) --------------------------------------------------------

async function* streamTurn(path: string, body?: unknown, signal?: AbortSignal): AsyncGenerator<ChatEvent> {
  let response: Response
  try {
    response = await fetch(`${AGENTS}${path}`, {
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

/** Streams the response to a user message on an existing conversation. The session id is
 * always explicit, so the message can only ever append to the thread the caller names —
 * create one first with createChatSession() for a brand-new chat. `attachmentUrl` is the
 * path returned by uploadImage() for a photo sent with this message; the chat server reads
 * that upload and hands it to the vision model. */
export function sendChatMessage(
  sessionId: string,
  message: string,
  signal?: AbortSignal,
  attachmentUrl?: string,
  documentIds?: string[]
): AsyncGenerator<ChatEvent> {
  // `documentIds` are the documents the user @-mentioned or attached as a PDF: the server checks them against the
  // caller's access and restricts this turn's document search to exactly them.
  const body = {
    message,
    ...(attachmentUrl ? { attachment_url: attachmentUrl } : {}),
    ...(documentIds && documentIds.length > 0 ? { document_ids: documentIds } : {}),
  }
  return streamTurn(`/chat/sessions/${sessionId}/messages`, body, signal)
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

export type { ChatEvent, ChatSessionSummary, StoredChatMessage }
