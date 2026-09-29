import { unavailable, type Unavailable } from "./not-implemented"
import type { ChatEvent, ChatMessage } from "@/lib/schemas/chat"

// No chat HTTP/SSE API exists on this backend (plans/07, 2026-09-29
// constraint: `backend` — which has the orchestrator's code but still no
// web server for it — is never merged into `frontend`). Same pattern as
// lib/api/documents.ts: typed stub, no fetch, always unavailable.

export function sendMessage(input: { text: string; approvalResponse?: "approve" | "modify" | "reject" }): Promise<Unavailable> {
  void input
  return unavailable()
}

export type { ChatEvent, ChatMessage }
