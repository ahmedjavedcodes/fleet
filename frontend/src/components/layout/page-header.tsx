"use client"

import { useEffect } from "react"
import { Breadcrumbs, type Crumb } from "@/components/primitives/breadcrumbs"
import { useTopbarSlots } from "./topbar-slots"

// A page renders <PageHeader/> next to its own data hooks to fill the
// topbar's breadcrumbs/status/actions (plans/03 §2) — it renders nothing
// itself. Re-registers on every render of the calling page (not just on
// navigation), so a status pill that only resolves once data loads still
// reaches the topbar.
export function PageHeader({
  crumbs,
  status,
  actions,
}: {
  crumbs: Crumb[]
  status?: React.ReactNode
  actions?: React.ReactNode
}) {
  const { setSlots, clearSlots } = useTopbarSlots()

  useEffect(() => {
    setSlots({ crumbs: <Breadcrumbs items={crumbs} />, status: status ?? null, actions: actions ?? null })
    return () => clearSlots()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [JSON.stringify(crumbs), status, actions, setSlots, clearSlots])

  return null
}
