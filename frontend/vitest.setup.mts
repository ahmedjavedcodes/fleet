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

// jsdom has neither ResizeObserver nor a non-zero layout box, both of which
// recharts' <ResponsiveContainer> needs to size its SVG — without these it
// silently renders 0x0 and none of the chart's contents mount at all. Some
// test files run under the "node" environment (server-only code has no DOM
// at all — see the @vitest-environment pragma on route/middleware tests),
// where `Element` itself doesn't exist, so this only applies when it does.
if (typeof Element !== "undefined") {
  class ResizeObserverStub {
    observe() {}
    unobserve() {}
    disconnect() {}
  }
  vi.stubGlobal("ResizeObserver", ResizeObserverStub);

  Element.prototype.getBoundingClientRect = () =>
    ({ width: 600, height: 300, top: 0, left: 0, bottom: 300, right: 600, x: 0, y: 0, toJSON() {} }) as DOMRect;
}
