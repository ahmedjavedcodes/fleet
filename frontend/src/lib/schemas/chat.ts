import { z } from "zod"
import { documentSearchHitSchema } from "./document"

// Mirrors the SSE contract in CLAUDE.md §5.5 for the `ai_agents` Grand
// Orchestrator. There is no HTTP/SSE server for it today (re-checked per
// plans/07's 2026-09-29 constraint: `backend` — which has the orchestrator's
// *code* but still no web server for it — is never merged into `frontend`
// anyway). Kept as the target contract; lib/api/chat.ts never opens a real
// connection against it.

export const agentKeySchema = z.enum(["foundation", "fuel", "maintenance", "accountability", "insights", "assignment", "search_documents", "update_memory"])
export type AgentKey = z.infer<typeof agentKeySchema>

export const hitlStateSchema = z.object({
  state: z.enum(["awaiting_approval", "halted", "done"]),
  pending_action: z.string().nullable(),
  approval_prompt: z.string().nullable(),
})
export type HitlState = z.infer<typeof hitlStateSchema>

export const activityEventSchema = z.object({
  type: z.literal("activity"),
  agent: agentKeySchema,
  step: z.string(),
  done: z.boolean(),
})
export const tokenEventSchema = z.object({ type: z.literal("token"), text: z.string() })
export const approvalRequiredEventSchema = z.object({ type: z.literal("approval_required"), hitl_state: hitlStateSchema })
export const citationsEventSchema = z.object({ type: z.literal("citations"), citations: z.array(documentSearchHitSchema) })
export const doneEventSchema = z.object({ type: z.literal("done") })
export const errorEventSchema = z.object({ type: z.literal("error"), message: z.string() })

export const chatEventSchema = z.discriminatedUnion("type", [
  activityEventSchema,
  tokenEventSchema,
  approvalRequiredEventSchema,
  citationsEventSchema,
  doneEventSchema,
  errorEventSchema,
])
export type ChatEvent = z.infer<typeof chatEventSchema>

export const chatMessageSchema = z.object({
  id: z.string(),
  role: z.enum(["user", "assistant"]),
  text: z.string(),
  citations: z.array(documentSearchHitSchema).optional(),
})
export type ChatMessage = z.infer<typeof chatMessageSchema>
