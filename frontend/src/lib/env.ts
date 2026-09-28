import "server-only"
import { z } from "zod"

// Validated lazily, on first property access, not at module-import time.
// `next build` imports route handler modules to collect their metadata
// (methods, `dynamic`/`runtime` exports) even for force-dynamic routes,
// without any real env vars set — an eager `envSchema.parse()` at the top of
// this file would crash the build itself. Accessing a property still fails
// immediately the first time any request handler actually runs (plans/02
// §2: "fails at boot, not at the first request") — middleware alone means
// that's the very first request the app ever serves.

const envSchema = z.object({
  API_BASE_URL: z.string().url(),
  SESSION_COOKIE_NAME: z.string().min(1).default("fleet_session"),
})

type Env = z.infer<typeof envSchema>

let cached: Env | undefined

function loadEnv(): Env {
  cached ??= envSchema.parse({
    API_BASE_URL: process.env.API_BASE_URL,
    SESSION_COOKIE_NAME: process.env.SESSION_COOKIE_NAME,
  })
  return cached
}

export const env: Env = new Proxy({} as Env, {
  get(_target, prop: string | symbol) {
    return loadEnv()[prop as keyof Env]
  },
})
