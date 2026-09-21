import { cleanup } from "@testing-library/react";
import { afterEach } from "vitest";

import "@testing-library/jest-dom/vitest";

// @testing-library/react's auto-cleanup relies on a global `afterEach`,
// which isn't registered since vitest.config.ts doesn't enable `test.globals`.
afterEach(() => {
  cleanup();
});
