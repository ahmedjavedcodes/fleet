"use client"

import { createContext, useCallback, useContext, useMemo, useState, type ReactNode } from "react"

// Implements plans/03 §2's "page header slot" concept — a page pushes its
// breadcrumbs/status/actions into the topbar without prop-drilling through
// the layout, and without the layout re-mounting on navigation. The plan
// names this a "portal", but a literal `ReactDOM.createPortal` into a
// `document.getElementById` target has real SSR-timing and
// duplicate-content hazards (the target doesn't exist during SSR, and
// there's no clean way for the topbar to know whether *any* page has
// portaled content yet, so it can render its pathname-derived fallback
// only when none has). A small Context-based slot registry gets the exact
// same outcome — PageHeader is still defined at the page, right next to its
// data hooks — without those hazards, so that's what this implements.

type Slots = { crumbs: ReactNode | null; status: ReactNode | null; actions: ReactNode | null }

const EMPTY_SLOTS: Slots = { crumbs: null, status: null, actions: null }

type TopbarSlotsValue = Slots & {
  setSlots: (next: Partial<Slots>) => void
  clearSlots: () => void
}

const TopbarSlotsContext = createContext<TopbarSlotsValue | null>(null)

export function TopbarSlotsProvider({ children }: { children: ReactNode }) {
  const [slots, setSlotsState] = useState<Slots>(EMPTY_SLOTS)

  // Stable across renders (functional updates only) so PageHeader's effect
  // never re-fires just because the provider's own state changed —
  // otherwise every setSlots call would produce a new setSlots reference,
  // re-triggering the effect that calls it, looping forever.
  const setSlots = useCallback((next: Partial<Slots>) => {
    setSlotsState((prev) => ({ ...prev, ...next }))
  }, [])
  const clearSlots = useCallback(() => setSlotsState(EMPTY_SLOTS), [])

  const value = useMemo<TopbarSlotsValue>(() => ({ ...slots, setSlots, clearSlots }), [slots, setSlots, clearSlots])

  return <TopbarSlotsContext.Provider value={value}>{children}</TopbarSlotsContext.Provider>
}

export function useTopbarSlots(): TopbarSlotsValue {
  const ctx = useContext(TopbarSlotsContext)
  if (!ctx) throw new Error("useTopbarSlots must be used within <TopbarSlotsProvider>")
  return ctx
}
