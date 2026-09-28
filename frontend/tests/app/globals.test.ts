import { readdirSync, readFileSync, statSync } from "fs"
import path from "path"
import { describe, expect, it } from "vitest"

// Computed from cwd (vitest runs from frontend/), not from this file's own
// location — it moved from src/app/ to tests/app/ when tests were reorganized
// into tests/, and __dirname-relative math would have silently pointed at
// tests/ instead of src/.
const SRC = path.resolve(process.cwd(), "src")
const css = readFileSync(path.join(SRC, "app/globals.css"), "utf8")

function block(selector: string): string {
  const start = css.indexOf(`${selector} {`)
  if (start === -1) throw new Error(`missing ${selector} block`)
  return css.slice(start, css.indexOf("\n}", start))
}

function definedVars(body: string): Set<string> {
  return new Set([...body.matchAll(/^\s*(--[\w-]+):/gm)].map((m) => m[1]))
}

describe("design tokens (CLAUDE.md §1.2)", () => {
  const themeInline = block("@theme inline")
  const root = definedVars(block(":root"))
  const dark = definedVars(block(".dark"))

  // Every runtime variable the theme maps to a utility must exist in :root.
  const referenced = [...themeInline.matchAll(/var\((--[\w-]+)\)/g)]
    .map((m) => m[1])
    .filter((v) => !v.startsWith("--font-") && v !== "--radius")

  it("defines every themed variable in the light set", () => {
    const missing = [...new Set(referenced)].filter((v) => !root.has(v))
    expect(missing).toEqual([])
  })

  it("overrides every themed color in the dark set, except values shared by design", () => {
    // Tiles, gauge gradient and severity aliases are intentionally theme-independent.
    const shared = /^--(tile-|gauge-start|gauge-end|sev-|elevation-card$|radius$|duration-)/
    const missing = [...new Set(referenced)].filter((v) => !shared.test(v) && !dark.has(v))
    expect(missing).toEqual([])
  })
})

describe("no raw design values in components (CLAUDE.md §1.2)", () => {
  function tsxFiles(dir: string): string[] {
    return readdirSync(dir).flatMap((name) => {
      const full = path.join(dir, name)
      if (statSync(full).isDirectory()) return tsxFiles(full)
      return full.endsWith(".tsx") ? [full] : []
    })
  }

  it.each(tsxFiles(SRC).map((f) => [path.relative(SRC, f), f]))("%s", (_rel, file) => {
    const source = readFileSync(file, "utf8")
    expect(source).not.toMatch(/#[0-9a-fA-F]{3,8}\b/)
    expect(source).not.toMatch(/-\[\d+(\.\d+)?(px|rem)\]/)
    expect(source).not.toMatch(/(bg|text|border|ring|fill|stroke|shadow)-\[(#|rgb|hsl|oklch)/)
  })
})
