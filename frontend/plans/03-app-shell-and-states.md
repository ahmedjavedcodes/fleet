# 03 — App Shell & Page States

**Goal:** the persistent authenticated shell (sidebar and topbar) exactly as in the
reference, the five page states every route needs, and the shared design primitives from
the component inventory in [00](00-design-analysis.md) §5. After this phase, a new page is
"fill in the content region".

**Depends on:** 01, 02. **Unblocks:** 04, 05, 06, 07.

---

## 1. Layout: `src/app/(app)/layout.tsx`

```
┌──────────────┬──────────────────────────────────────────────────────┐
│  Sidebar     │  Topbar: Breadcrumbs · [page status] · [page actions] │ Bell · UserMenu? │
│  (sticky,    ├──────────────────────────────────────────────────────┤
│   full-h)    │  <main id="content"> page </main>                     │
└──────────────┴──────────────────────────────────────────────────────┘
```

- A Server Component. It reads the session via `getServerMe()` and prefetches `/auth/me` into
  a `HydrationBoundary`, so the sidebar's user card paints without a flash.
- The sidebar and topbar are detached, rounded, bordered white cards on the white page, with
  a gap between them (per the reference). The page gutter uses the spacing token (≈16px).
- Owns the app-level error boundary (`src/app/(app)/error.tsx` as the fallback), the
  `<Toaster />` placement, and a "Skip to content" link.
- **Never re-mounts on navigation.** The layout lives in the route group, and pages only
  swap `children`.

## 2. Page header slots

Breadcrumbs, a status pill and page actions differ per page (the reference shows all three).
Give each page a declarative way to fill them without prop-drilling through the layout.

- `src/components/layout/page-header.tsx` exports `<PageHeader crumbs={[…]} status={<StatusPill…/>} actions={<…/>} />`.
- It renders through a portal into topbar slots (`#topbar-crumbs`, `#topbar-status`,
  `#topbar-actions`). The alternative is a Next parallel route `@header`; **pick the portal**
  because it keeps a page's header next to its own data hooks. Record the choice in
  CLAUDE.md §2.3.
- Fallback when a page renders no header: crumbs derived from the pathname via a
  `routeLabels` map.

## 3. Sidebar: `src/components/layout/sidebar.tsx`

| Detail | Spec |
| --- | --- |
| Brand | Truck mark in `--primary` + the wordmark **"FleetOps"**, in the same weight and size as the reference's "FleetYo." ("FleetYo" is the reference's brand, not ours). Keep the name in one constant (`src/lib/brand.ts`: `APP_NAME = "FleetOps"`), reused by the login page, `<title>` metadata and the sidebar. In the collapsed sidebar, show only the mark, with `aria-label="FleetOps"`. |
| Collapse toggle | `PanelLeft` icon button, top right of the sidebar. The collapsed state persists in `localStorage` (a UI preference, which CLAUDE.md §4.5 allows since it holds no token or org data). |
| Groups | From [00](00-design-analysis.md) §4: a muted small label, items, then a divider between groups. Groups with no visible items are hidden entirely. |
| Item | Lucide icon (20px) + label. Hover `bg-muted`. **Active**: `bg-primary-soft`, `text-primary-strong`, icon `text-primary`, with `aria-current="page"`. Prefix match on `usePathname()`. |
| Filtering | `can(role, "nav:<route>")`. While `/auth/me` is loading, render skeleton items, not the full list, so nav items never flash in and then out. |
| User card | Bottom, bordered: `InitialsAvatar`, `full_name`, role label, and a `ChevronsUpDown` that opens the **user menu** (see 4). This replaces a topbar avatar, following the reference. |
| Responsive | ≥ `xl`: expanded (≈ 300px). `lg`: icon-only with tooltips. < `lg`: hidden, and a hamburger in the topbar opens it as a shadcn `Sheet`. |
| Prefetch | `<Link prefetch>` on hover (CLAUDE.md §6). |

## 4. Topbar: `src/components/layout/topbar.tsx`

Left to right:

1. **Hamburger** (< `lg` only).
2. **Breadcrumbs** (`#topbar-crumbs`). On small screens, truncate the middle crumbs to `…`.
3. **Status slot** (`#topbar-status`): a `StatusPill`, optional per page.
4. **Actions slot** (`#topbar-actions`): outline `ActionButton`s with icon + label (label hidden
   < `md`, keeping `aria-label`), then a vertical `Separator`, then square icon buttons.
5. **Notification bell**: Lucide `Bell` as a square icon button, with a popover that says
   "Notifications aren't available yet" and links to `/notifications`. **No badge, no count**
   until the API exists (CLAUDE.md §3, §5.5).

**User menu** (opened from the sidebar user card; on mobile, from the card inside the
Sheet): a `DropdownMenu` with the name, role badge and `organization.name`, then **Sign out**
(`POST /api/auth/logout` → `queryClient.clear()` → `/login`).

*Profile* is listed in CLAUDE.md §3 but has no page or endpoint beyond `/auth/me`. **Omit it
until a profile page exists** (no dead UI), and note this in CLAUDE.md §3.

## 5. Page states: `src/components/states/`

| Component | Visual (tokens only) | Props | Used for |
| --- | --- | --- | --- |
| `PageSkeleton` + shape helpers `SkeletonKpiGrid`, `SkeletonTable rows={n}`, `SkeletonChart`, `SkeletonPanel` | shadcn `Skeleton` blocks shaped like the final content | layout-specific | `loading.tsx` of every route, and `isPending` of each data region |
| `EmptyState` | `IconTile` (muted), title, one-line explanation, optional primary action | `icon, title, description, action?` | An empty list. The action renders only if `can()` allows it |
| `ErrorState` | Destructive-soft icon, a human message from `ApiError`, **Retry** | `error: ApiError, onRetry` | Switches on `error.kind`: 404 → not-found copy, 409 → conflict + Refresh, 429 → wait copy, 503 → temporarily unavailable, schema → "unexpected response" (details go to the console only) |
| `AccessDenied` | Lock icon, "You don't have access to {area}", role-aware hint ("Available to Admins and Fleet Managers"), link back to `/dashboard` | `area, allowedRoles` | A page-level 403 or `!routeAccess()`. **Never retried** |
| `NotAvailableYet` | Info-soft icon, honest copy ("This feature is waiting on its backend API") | `feature` | Features from CLAUDE.md §5.5 (chat, notifications, NL insights) |

Plus `src/components/states/query-boundary.tsx`: a `<QueryRegion query={q} skeleton={…} empty={…} isEmpty={(d) => d.length === 0}>{(data) => …}</QueryRegion>` helper, so every data region handles all five states the same way.

**Route guard:** `src/components/layout/route-guard.tsx` wraps a page's content and renders
`AccessDenied` when `routeAccess(role, pathname)` is false. It is still the fallback: a
403 from any query also renders `AccessDenied` for that region.

## 6. Shared design primitives

Build the shared rows from the component inventory in 00 §5 now, because plans 04 to 07 all
depend on them:

- `SectionPanel`, `InnerCard`, `KpiTile`, `IconTile`, `StatusPill`
- `Breadcrumbs`, `ActionButton` (Button variants), `DataTable`, `InitialsAvatar`

Rules:

- Each component stays under ≈200 lines, has one export and uses tokens only.
- `KpiTile` value formatting takes a formatter prop (money / number / count). The unit is
  rendered in `text-muted-foreground`, smaller than the value (not the `#D8D7D8` of the
  reference, which fails AA).
- `DataTable`:
  - sticky header, right-aligned `tabular-nums` numerics, and headers that state units;
  - sortable columns via TanStack Table when needed;
  - client pagination beyond 50 rows (the backend doesn't paginate most lists).
- `StatusPill` variants: `success`, `warning`, `info`, `neutral`, `destructive`, `sev-*`, each
  with a dot and text. Color is never the only signal.

## 7. Route scaffolding

Create every route directory from the CLAUDE.md §2.1 route map (updated in 01), each with
`page.tsx`, `loading.tsx` and `error.tsx`. Until its plan lands, a page renders its
`PageHeader` and a `NotAvailableYet` or `EmptyState`. This counts as an honest state, not
dead UI, but **keep it out of the nav** until the page has real content. The exception is
§5.5 features, which show "not available yet" by design.

## 8. Tests

- Sidebar: renders the right groups and items for each of the 4 roles (driven by the `rbac`
  matrix); marks the active item with `aria-current`; hides empty groups.
- User menu: name, role label, org name; Sign out calls logout and clears the cache.
- Bell: no badge rendered.
- `ErrorState`: each `ApiError.kind` renders the right copy and Retry behavior (none for 403).
- `AccessDenied`, `EmptyState` (action hidden without permission), `QueryRegion` (all five
  states).

## 9. Exit criteria

- [ ] Log in as each role: the nav matches the matrix; opening a hidden route by URL shows
      `AccessDenied`.
- [ ] 1440px: matches the reference's shell (spacing, active state, user card). 1024px:
      icon-only sidebar. 375px: Sheet drawer, no horizontal scroll.
- [ ] Keyboard: Tab order is skip-link → nav → topbar → content; focus rings are visible;
      Esc closes the Sheet and menus.
- [ ] build, lint and tests pass.
