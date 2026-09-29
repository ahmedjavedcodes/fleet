// Shared result shape for an adapter whose backend doesn't exist yet
// (documents, chat, notifications — CLAUDE.md §5.5). Every function in one
// of these adapters resolves to this literal, synchronously wrapped in a
// Promise, and never calls fetch — so there's nothing to point at a real
// endpoint by mistake, and the type system forces every caller to check
// `.status` before touching a `data` field that doesn't exist here.
export type Unavailable = { status: "unavailable" }

export function unavailable(): Promise<Unavailable> {
  return Promise.resolve({ status: "unavailable" })
}
