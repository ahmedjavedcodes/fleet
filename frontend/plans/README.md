# Frontend Plans

Phased roadmap for building `frontend/` from the setup-only state (commit `d31f603`) to the
full dashboard described in [../CLAUDE.md](../CLAUDE.md).

**Precedence:** [CLAUDE.md](../CLAUDE.md) is the contract. If a plan here disagrees with it,
CLAUDE.md wins and the plan gets fixed. Plans that change the contract (routes, tokens) do
so by editing CLAUDE.md as an explicit step, never implicitly.

**Design reference:** [assets/fleetyo-vehicle-detail.png](assets/fleetyo-vehicle-detail.png)
(a vehicle-detail screen). Its analysis, measured tokens and conflicts with CLAUDE.md
are in [00-design-analysis.md](00-design-analysis.md). Read that first.

---

## Phases

| # | Plan | Depth | Depends on | Status |
| --- | --- | --- | --- | --- |
| 00 | [Design analysis](00-design-analysis.md) | Reference | — | Done |
| 01 | [Setup & design system](01-setup-and-design-system.md) | Detailed | 00 | ✅ Done (2026-09-25) |
| 02 | [Auth (BFF) & API layer](02-auth-bff-and-api-layer.md) | Detailed | 01 | ✅ Done (2026-09-28) |
| 03 | [App shell & page states](03-app-shell-and-states.md) | Detailed | 01, 02 | ✅ Done (2026-09-28) |
| 04 | [Dashboard](04-dashboard.md) | Detailed | 03 | ✅ Done (2026-09-29) |
| 05 | [Foundation & vehicle detail](05-foundation-and-vehicle-detail.md) | Detailed | 03 | ⚠️ Built, not live-verified (2026-09-29) |
| 06 | [Operations modules](06-operations-modules.md) | Scoped | 03 | ☐ Not started |
| 07 | [AI surfaces](07-ai-surfaces.md) | Scoped | 03 | ☐ Not started |

```
01 ──► 02 ──► 03 ──┬──► 04
                   ├──► 05   (04, 05, 06 can run in parallel)
                   ├──► 06
                   └──► 07
```

"Scoped" plans list the endpoints, role matrix, UI and domain rules, but not a per-component
breakdown. Expand a scoped plan to "Detailed" before starting it, since the backend may
have moved by then.

## Done means (every phase)

From CLAUDE.md §7:

- `npm run build`, `npm run lint` and `npm test` all pass, with zero type or lint errors.
- Checked in a real browser at **375px** and **1440px**, for every role that can see the page.
- Loading, empty, error, access-denied (and "not available yet" where relevant) states verified.
- Any route, endpoint or token change is reflected in CLAUDE.md in the same change (§8).

## Local development

| What | How |
| --- | --- |
| Backend | FastAPI at `http://localhost:8000`. CORS already allows `http://localhost:3000` with credentials (`backend/app/core/config.py`, override via `CORS_ORIGINS`). |
| Frontend | `npm run dev` in `frontend/` → `http://localhost:3000` |
| Test users | From `backend/`: `.venv\Scripts\python seed_test_users.py` (idempotent) |

The seeder creates org **`fleet-registry-agent-test`** with four users, all with password
`TestPass123!`:

| Role | Email |
| --- | --- |
| Admin | `admin@fleet-registry-agent-test.dev` |
| Fleet Manager | `fleet_manager@fleet-registry-agent-test.dev` |
| Driver | `driver@fleet-registry-agent-test.dev` |
| Mechanic | `mechanic@fleet-registry-agent-test.dev` |

**Seeder caveats:**

- It creates **no vehicles, drivers or any other data**. Every list starts empty, which is a
  good test of the empty states, but pages with real data need records created
  through the UI or the API.
- The seeded driver has **no linked Driver profile**: `/auth/me` returns
  `driver_profile: null`, the driver's fuel, trip and report lists are empty, and
  `POST /fuel` returns 422. The Driver dashboard must design for this case (see plan 04).
