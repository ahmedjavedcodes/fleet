import { render, type RenderOptions } from "@testing-library/react"
import { TopbarSlotsProvider } from "@/components/layout/topbar-slots"
import { TooltipProvider } from "@/components/ui/tooltip"

// Any page/component using <PageHeader> needs a <TopbarSlotsProvider>
// ancestor — (app)/layout.tsx supplies it for real, but a unit test that
// renders a page component in isolation needs the same context or
// useTopbarSlots() throws. KpiTile's hint tooltip likewise needs a
// <TooltipProvider> ancestor, normally supplied by the root providers.
// Reused by every such test rather than each wrapping its own render calls.
function AllProviders({ children }: { children: React.ReactNode }) {
  return (
    <TooltipProvider>
      <TopbarSlotsProvider>{children}</TopbarSlotsProvider>
    </TooltipProvider>
  )
}

export function renderWithProviders(ui: React.ReactElement, options?: Omit<RenderOptions, "wrapper">) {
  return render(ui, { wrapper: AllProviders, ...options })
}
