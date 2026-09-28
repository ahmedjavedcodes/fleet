import path from "path";
import { fileURLToPath } from "url";

import react from "@vitejs/plugin-react";
import { defineConfig } from "vitest/config";

const dirname = path.dirname(fileURLToPath(import.meta.url));

export default defineConfig({
  plugins: [react()],
  test: {
    environment: "jsdom",
    setupFiles: ["./vitest.setup.mts"],
    css: false,
    // The default "forks" pool times out spawning child processes in some
    // sandboxed dev environments (observed on this project); "threads" is
    // just as isolated for our purposes and doesn't have that problem.
    pool: "threads",
  },
  resolve: {
    alias: {
      "@": path.resolve(dirname, "./src"),
    },
  },
});
