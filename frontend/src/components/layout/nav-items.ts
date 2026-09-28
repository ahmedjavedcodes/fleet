import {
  ArrowLeftRight,
  Bell,
  Building2,
  ChartColumn,
  FileText,
  Fuel,
  LayoutGrid,
  ShieldAlert,
  Sparkles,
  Truck,
  Users,
  Wrench,
  type LucideIcon,
} from "lucide-react"

// Mirrors CLAUDE.md §3's sidebar table exactly. Reference 1's "Live
// Tracking", "Route", "Tasks", "Reports" and "Settings" are deliberately
// not here (telemetry, or no such domain — plans/00 §3).
export type NavItem = { label: string; href: string; icon: LucideIcon }
export type NavGroup = { label: string; items: NavItem[] }

export const NAV_GROUPS: NavGroup[] = [
  {
    label: "Main Menu",
    items: [
      { label: "Overview", href: "/dashboard", icon: LayoutGrid },
      { label: "AI Assistant", href: "/chat", icon: Sparkles },
    ],
  },
  {
    label: "Fleet",
    items: [
      { label: "Vehicles", href: "/foundation/vehicles", icon: Truck },
      { label: "Drivers", href: "/foundation/drivers", icon: Users },
      { label: "Suppliers", href: "/foundation/suppliers", icon: Building2 },
      { label: "Assignment", href: "/assignment", icon: ArrowLeftRight },
    ],
  },
  {
    label: "Operations",
    items: [
      { label: "Fuel & Trips", href: "/fuel", icon: Fuel },
      { label: "Maintenance", href: "/maintenance", icon: Wrench },
      { label: "Accountability", href: "/accountability", icon: ShieldAlert },
    ],
  },
  {
    label: "Knowledge",
    items: [{ label: "Documents", href: "/documents", icon: FileText }],
  },
  {
    label: "Insights",
    items: [{ label: "Insights", href: "/insights", icon: ChartColumn }],
  },
  {
    label: "Monitoring",
    items: [{ label: "Notifications", href: "/notifications", icon: Bell }],
  },
]
