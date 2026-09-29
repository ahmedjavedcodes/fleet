import { unavailable, type Unavailable } from "./not-implemented"

// AlertDispatcher only logs today — there's no notifications API (CLAUDE.md
// §5.5). Same stub pattern as documents/chat: no fetch, always unavailable.

export function listWarnings(): Promise<Unavailable> {
  return unavailable()
}

export function listNotifiedEvents(): Promise<Unavailable> {
  return unavailable()
}

export function listTriggers(): Promise<Unavailable> {
  return unavailable()
}
