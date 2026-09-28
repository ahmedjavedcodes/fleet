import { longestPrefixMatch } from "./longest-prefix-match"

// The nav-item labels from CLAUDE.md §3's sidebar table, reused as the
// fallback breadcrumb / AccessDenied "area" text when a page renders no
// PageHeader of its own (plans/03 §2).
const ROUTE_LABELS: readonly { prefix: string; label: string }[] = [
  { prefix: "/dashboard", label: "Overview" },
  { prefix: "/chat", label: "AI Assistant" },
  { prefix: "/foundation/vehicles", label: "Vehicles" },
  { prefix: "/foundation/drivers", label: "Drivers" },
  { prefix: "/foundation/suppliers", label: "Suppliers" },
  { prefix: "/foundation", label: "Foundation" },
  { prefix: "/assignment", label: "Assignment" },
  { prefix: "/fuel", label: "Fuel & Trips" },
  { prefix: "/maintenance", label: "Maintenance" },
  { prefix: "/accountability", label: "Accountability" },
  { prefix: "/documents", label: "Documents" },
  { prefix: "/insights", label: "Insights" },
  { prefix: "/notifications", label: "Notifications" },
]

export function routeLabel(pathname: string): string {
  return longestPrefixMatch(ROUTE_LABELS, pathname)?.label ?? "FleetOps"
}
