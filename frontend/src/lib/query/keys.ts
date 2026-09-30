// One factory per domain (CLAUDE.md §5.1). Components never write inline key
// arrays — every hook builds its key from here, so invalidation calls
// (plans/02 §7, CLAUDE.md §5.1) can target precisely the right queries.
//
// Filter/param arguments are genuinely OMITTED from the key array when not
// passed (never defaulted to `{}` inside the factory) — TanStack Query's
// partial-match invalidation only prefix-matches a *shorter* key array
// against a longer cached one. `xKeys.list()` (no argument) therefore
// invalidates every cached variant of that list, however it was filtered;
// `xKeys.list(filters)` addresses one specific cached query. Do not add a
// default value to any parameter below — that would silently defeat this.

export const meKeys = {
  all: ["me"] as const,
  current: () => [...meKeys.all, "current"] as const,
}

export const vehicleKeys = {
  all: ["vehicles"] as const,
  // GET /vehicles takes no query params on the backend today.
  list: () => [...vehicleKeys.all, "list"] as const,
  detail: (id: string) => [...vehicleKeys.all, "detail", id] as const,
  timeline: (id: string) => [...vehicleKeys.all, id, "timeline"] as const,
  compliance: (id: string) => [...vehicleKeys.all, id, "compliance"] as const,
  assignments: (id: string, targetDate?: string) =>
    targetDate === undefined
      ? ([...vehicleKeys.all, id, "assignments"] as const)
      : ([...vehicleKeys.all, id, "assignments", targetDate] as const),
}

export const driverKeys = {
  all: ["drivers"] as const,
  // GET /drivers takes no query params on the backend today.
  list: () => [...driverKeys.all, "list"] as const,
  detail: (id: string) => [...driverKeys.all, "detail", id] as const,
  timeline: (id: string) => [...driverKeys.all, id, "timeline"] as const,
  assignments: (id: string) => [...driverKeys.all, id, "assignments"] as const,
}

export const supplierKeys = {
  all: ["suppliers"] as const,
  list: (sort?: string) =>
    sort === undefined ? ([...supplierKeys.all, "list"] as const) : ([...supplierKeys.all, "list", sort] as const),
}

export const fuelKeys = {
  all: ["fuel"] as const,
  list: (filters?: Record<string, unknown>) =>
    filters === undefined ? ([...fuelKeys.all, "list"] as const) : ([...fuelKeys.all, "list", filters] as const),
  detail: (id: string) => [...fuelKeys.all, "detail", id] as const,
  summary: (month?: string) =>
    month === undefined ? ([...fuelKeys.all, "summary"] as const) : ([...fuelKeys.all, "summary", month] as const),
}

export const tripKeys = {
  all: ["trips"] as const,
  list: (filters?: Record<string, unknown>) =>
    filters === undefined ? ([...tripKeys.all, "list"] as const) : ([...tripKeys.all, "list", filters] as const),
  detail: (id: string) => [...tripKeys.all, "detail", id] as const,
}

export const maintenanceKeys = {
  all: ["maintenance"] as const,
  list: (filters?: Record<string, unknown>) =>
    filters === undefined
      ? ([...maintenanceKeys.all, "list"] as const)
      : ([...maintenanceKeys.all, "list", filters] as const),
  detail: (id: string) => [...maintenanceKeys.all, "detail", id] as const,
  upcoming: (windowKm?: number) =>
    windowKm === undefined
      ? ([...maintenanceKeys.all, "upcoming"] as const)
      : ([...maintenanceKeys.all, "upcoming", windowKm] as const),
  overdue: () => [...maintenanceKeys.all, "overdue"] as const,
}

export const complianceKeys = {
  all: ["compliance"] as const,
  rules: (filters?: Record<string, unknown>) =>
    filters === undefined
      ? ([...complianceKeys.all, "rules"] as const)
      : ([...complianceKeys.all, "rules", filters] as const),
  statusMatrix: () => [...complianceKeys.all, "status"] as const,
  statusFor: (vehicleId: string) => [...complianceKeys.all, "status", vehicleId] as const,
}

export const inventoryKeys = {
  all: ["inventory"] as const,
  list: (filters?: Record<string, unknown>) =>
    filters === undefined
      ? ([...inventoryKeys.all, "list"] as const)
      : ([...inventoryKeys.all, "list", filters] as const),
  lowStock: () => [...inventoryKeys.all, "low-stock"] as const,
}

export const purchaseOrderKeys = {
  all: ["purchase-orders"] as const,
  list: (filters?: Record<string, unknown>) =>
    filters === undefined
      ? ([...purchaseOrderKeys.all, "list"] as const)
      : ([...purchaseOrderKeys.all, "list", filters] as const),
}

export const incidentKeys = {
  all: ["incidents"] as const,
  list: (filters?: Record<string, unknown>) =>
    filters === undefined
      ? ([...incidentKeys.all, "list"] as const)
      : ([...incidentKeys.all, "list", filters] as const),
  detail: (id: string) => [...incidentKeys.all, "detail", id] as const,
}

export const driverReportKeys = {
  all: ["driver-reports"] as const,
  list: (filters?: Record<string, unknown>) =>
    filters === undefined
      ? ([...driverReportKeys.all, "list"] as const)
      : ([...driverReportKeys.all, "list", filters] as const),
}

export const dashboardKeys = {
  all: ["dashboard"] as const,
  summary: () => [...dashboardKeys.all, "summary"] as const,
  fuelTrends: (months?: number) =>
    months === undefined
      ? ([...dashboardKeys.all, "fuel-trends"] as const)
      : ([...dashboardKeys.all, "fuel-trends", months] as const),
  maintenanceCalendar: (windowDays?: number) =>
    windowDays === undefined
      ? ([...dashboardKeys.all, "maintenance-calendar"] as const)
      : ([...dashboardKeys.all, "maintenance-calendar", windowDays] as const),
  fleetHealth: () => [...dashboardKeys.all, "fleet-health"] as const,
}

export const documentKeys = {
  all: ["documents"] as const,
  list: () => [...documentKeys.all, "list"] as const,
  chunks: (id: string) => [...documentKeys.all, "chunks", id] as const,
}

export const notificationKeys = {
  all: ["notifications"] as const,
  list: () => [...notificationKeys.all, "list"] as const,
}

export const chatKeys = {
  all: ["chat"] as const,
  sessions: () => [...chatKeys.all, "sessions"] as const,
  messages: (id: string) => [...chatKeys.all, "messages", id] as const,
}
