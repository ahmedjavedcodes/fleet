import { z } from "zod"
import { documentSearchHitSchema } from "./document"

// Mirrors ai_agents/orchestrator/{session,state}.py exactly (verified
// against that code directly, not guessed) — this is now a live contract:
// ai_agents/server.py wraps OrchestratorSession in a real HTTP/SSE API,
// proxied through /api/proxy-agents. Re-verify against those two files if
// either changes (CLAUDE.md §8).

export const agentKeySchema = z.enum(["foundation", "fuel", "maintenance", "accountability", "insights", "assignment", "search_documents", "update_memory"])
export type AgentKey = z.infer<typeof agentKeySchema>

// orchestrator/state.py's HitlState TypedDict — `state` here is the paused
// sub-agent's own state (for rendering), not a status enum.
export const hitlStateSchema = z.object({
  agent_name: z.string(),
  thread_id: z.string(),
  tool_name: z.string().optional(),
  pending_node: z.string().optional(),
  state: z.record(z.string(), z.unknown()).optional(),
  approval_prompt: z.string().optional(),
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
// orchestrator/session.py's TurnResult.status — "halted" included, since a
// security/off-topic rejection or a HITL reject both settle with status
// "halted" and a message already streamed as `token`s, not a separate error.
export const doneEventSchema = z.object({ type: z.literal("done"), status: z.enum(["done", "halted"]) })
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
