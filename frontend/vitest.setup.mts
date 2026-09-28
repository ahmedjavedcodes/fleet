import { cleanup } from "@testing-library/react";
import { afterEach, vi } from "vitest";

import "@testing-library/jest-dom/vitest";

// @testing-library/react's auto-cleanup relies on a global `afterEach`,
// which isn't registered since vitest.config.ts doesn't enable `test.globals`.
afterEach(() => {
  cleanup();
});

// The `server-only` package throws unconditionally when resolved without
// Next's build-time "react-server" export condition, which Vitest doesn't
// set — so importing it here would always throw, in any environment,
// regardless of whether the code under test is genuinely server-only. That
// guarantee ("never bundled into the client") is a Next.js build-time
// property enforced by its bundler, not something a unit test re-verifies;
// tests care about the guarded module's logic, so this makes it a no-op.
vi.mock("server-only", () => ({}));
