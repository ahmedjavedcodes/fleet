# 01 — Setup & Design System

**Goal:** turn the setup-only `frontend/` into a themed, provider-wrapped Next.js app, with
every token from [00-design-analysis.md](00-design-analysis.md) §2 defined once in
`globals.css`. By the end, a component can be built using only semantic utilities and look
like the reference.

**Depends on:** 00. **Unblocks:** 02, 03.

---

## 1. Dependencies

```bash
cd frontend
npm install @tanstack/react-query @tanstack/react-query-devtools react-markdown remark-gfm
npx shadcn@latest init        # Tailwind v4 + React 19; CSS variables: yes; base color: neutral
npx shadcn@latest add button card badge dialog dropdown-menu sheet tabs table tooltip \
  hover-card skeleton sonner avatar separator scroll-area progress
```

Also add, since later phases need them and shadcn's list is not exhaustive:

- `input`, `label`, `select`, `textarea`, `form`, `popover`, `alert-dialog` (confirm dialogs,
  CLAUDE.md §6), `breadcrumb`, `toggle-group` (7/30/90-day range picker)
- `msw` (dev dependency) for HTTP-boundary mocks in tests (CLAUDE.md §7)

Check afterwards:

- `components.json` points at `src/components/ui` and `@/lib/utils`.
- `shadcn init` did **not** overwrite `postcss.config.mjs` in a way that breaks
  `@tailwindcss/postcss`.
- No second icon library was pulled in (shadcn uses `lucide-react`, which is correct).

## 2. Design tokens: `src/app/globals.css`

`globals.css` is the only CSS file. Structure:

```css
@import "tailwindcss";
@custom-variant dark (&:is(.dark *));

:root { /* light values (00 §2) */ }
.dark { /* derived dark values */ }

@theme inline {
  /* map every variable to a Tailwind utility:
     --color-primary: var(--primary); --radius-lg: var(--radius); ... */
}
```

### Tokens to define

| Group | Variables |
| --- | --- |
| shadcn semantic | `--background`, `--foreground`, `--card`, `--card-foreground`, `--popover`, `--popover-foreground`, `--primary`, `--primary-foreground`, `--secondary`, `--secondary-foreground`, `--muted`, `--muted-foreground`, `--accent`, `--accent-foreground`, `--destructive`, `--border`, `--input`, `--ring`, `--sidebar*` |
| Brand extensions | `--primary-strong`, `--primary-soft` |
| Surfaces | `--panel` (outer grey panel), `--table-head` (only if distinct from `--muted`) |
| Status | `--success`, `--success-strong` (text), `--success-soft`, `--warning`, `--warning-soft`, `--warning-border`, `--warning-icon`, `--info`, `--destructive` |
| Severity | `--sev-minor`, `--sev-moderate`, `--sev-severe`, `--sev-critical` (+ `-soft` variants for pill backgrounds) |
| KPI tiles | `--tile-green`, `--tile-blue`, `--tile-amber`, `--tile-purple` |
| Charts | `--chart-1` … `--chart-5`, `--chart-grid` |
| Gauge | `--gauge-start`, `--gauge-end`, `--gauge-track` |
| Radius | `--radius` (= lg, 12px) with `sm`/`md`/`lg`/`xl`/`2xl` derived; `xl` = 16px for outer cards |
| Elevation | `--shadow-card: none`, `--shadow-card-hover`, `--shadow-popover` (derived) |
| Motion | `--ease-standard`, `--duration-hover: 150ms`, `--duration-overlay: 200ms` |
| Fonts | `--font-sans` (Urbanist), `--font-mono` |

**Primary button decision.** White text on `#F5781E` is 2.8:1, which fails AA. The
`default` button variant therefore uses `--primary-strong` as its background, and `--primary`
stays the fill for icons, chart strokes, the focus ring and the logo.

### Reduced motion

A global `@media (prefers-reduced-motion: reduce)` block disables the pulse and glow
keyframes (used later by AgentActivity) and shortens transitions to 0ms.

### Before the values become final

1. **Re-measure** radius, spacing and type scale from the PNG. Scan corners and gaps at
   known coordinates, as was done for colors; record the values in 00 §2.
2. **Contrast check** every text/background pair in light *and* dark, including:
   - `--primary-strong` on `--background` and on `--primary-soft` (active nav);
   - `--muted-foreground` on `--panel`;
   - `--success-strong` on `--success-soft`;
   - white on every `--tile-*` (3:1 for icons);
   - every `--chart-*` on `--card` (3:1 for strokes).

   Record each ratio in CLAUDE.md §1.2.
3. Validate the chart palette with the `dataviz` skill's checker.

## 3. Customize shadcn to the design

Edit the copied source in `src/components/ui/` directly; never wrap it with overrides
(CLAUDE.md §0).

| Component | Changes |
| --- | --- |
| `button` | Variants: `default` (`--primary-strong`), `outline` (white, `--border`, dark text; the topbar "Contact Driver" style), `ghost`, `destructive`, `link`. Sizes include `icon` (square, the topbar flag/share style). Radius `lg`. |
| `card` | `rounded-xl border bg-card shadow-card` (no shadow). Header: `flex items-center gap-2`, title 20px medium. |
| `badge` | Add variants `success`, `warning`, `info`, `sev-*`: soft background + strong text + optional dot. |
| `table` | Header row on `--table-head`/`--muted`, `sticky top-0`, `text-muted-foreground` headers, `tabular-nums` cells, row hover `bg-muted/50`. |
| `sidebar` (if using shadcn's) | Active item: `bg-primary-soft text-primary-strong`, with the icon in `text-primary`. |

## 4. App root

- `src/app/layout.tsx`:
  - `<html lang="en">`, Urbanist from `next/font/google` exposed as `--font-sans`, and the
    mono font as `--font-mono`;
  - `<body className="bg-background text-foreground font-sans antialiased">`;
  - wraps children in `<Providers>`.
- `src/app/providers.tsx` (`"use client"`):
  - `QueryClientProvider` with the client from `lib/query/client.ts` (the defaults are
    specified in plan 02; a minimal client is fine here);
  - `ReactQueryDevtools` in development only;
  - `<Toaster />` (sonner).
- `src/lib/brand.ts`: `export const APP_NAME = "FleetOps"`. Root `metadata` uses it
  (`title: { default: "FleetOps", template: "%s · FleetOps" }`), so every page tab reads
  "Vehicles · FleetOps".
- `src/app/page.tsx`: `redirect("/dashboard")`.
- **Dark mode:** a `.dark` class on `<html>`. A theme toggle is not in the reference, so it is
  **not** built now: the dark set exists so it can be switched on later without redesign.

## 5. Update CLAUDE.md (same change)

- **§1.1:** row 1 = `frontend/plans/assets/fleetyo-vehicle-detail.png`, with "shell, sidebar
  active state, KPI tiles, panels, charts, gauge, callouts, tables" as what to take from it.
  Rows 2–4 stay TBD (chat/AI surfaces have no reference yet).
- **§1.2:** replace every `_TBD_` with the final values. Mark derived values (dark set,
  destructive, severity, motion, popover shadow) as *derived*.
- **§2.1:** replace the single `/foundation` row with `/foundation/vehicles`,
  `/foundation/vehicles/[id]`, `/foundation/drivers`, `/foundation/drivers/[id]` and
  `/foundation/suppliers`; add the nav grouping from 00 §4.
- **§2.3:** add `src/app/providers.tsx` to the file layout.

## 6. Exit criteria

- [x] `npm run build`, `npm run lint`, `npm test` pass.
- [x] A temporary dev-only `/dev-tokens` page (not `/_tokens`: `_`-prefixed folders are private in the App Router) shows every token as a swatch, plus buttons,
      badges, a card and a table in both themes. Compare it against the PNG side by side, then
      **delete the page** (no dead UI in committed code).
- [x] Contrast ratios are recorded in CLAUDE.md §1.2; no pair fails AA.
- [x] No raw hex or arbitrary values outside `globals.css` (enforced by `src/app/globals.test.ts`):
      `grep -rE "#[0-9a-fA-F]{3,6}|\[[0-9]+px\]" src --include=*.tsx` returns nothing.
