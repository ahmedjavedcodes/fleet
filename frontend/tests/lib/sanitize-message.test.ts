import { describe, expect, it } from "vitest"
import { hasToolMarkup, stripToolMarkup } from "@/lib/sanitize-message"

const BAR = "｜" // the fullwidth bar DeepSeek's special tokens are written with

function dsml(name = "fuel", params: Record<string, string> = {}): string {
  const inner = Object.entries(params)
    .map(([k, v]) => `<${BAR}DSML${BAR}parameter name="${k}" string="true">${v}</${BAR}DSML${BAR}parameter>`)
    .join("")
  return `<${BAR}DSML${BAR}tool_calls><${BAR}DSML${BAR}invoke name="${name}">${inner}</${BAR}DSML${BAR}invoke></${BAR}DSML${BAR}tool_calls>`
}

// The text from the bug report.
const REPORTED = dsml("fuel", {
  query_entity: "add_fill",
  vehicle_id: "132415a0-8f72-47b0-9bf4-5bb093b8a9a9",
  liters: "50",
  price_per_liter: "280",
})

describe("stripToolMarkup", () => {
  it.each<[string, string, string]>([
    ["the reported DSML reply", REPORTED, ""],
    ["DSML written with ASCII bars", REPORTED.replaceAll(BAR, "|"), ""],
    ["DSML beside real text", `I'll log that now.\n\n${REPORTED}\n\nDone.`, "I'll log that now.\n\nDone."],
    ["a DSML call cut off mid-way", `Sure. <${BAR}DSML${BAR}tool_calls><${BAR}DSML${BAR}invoke name="x">`, "Sure."],
    ["a special token still arriving", `Logging it <${BAR}DSM`, "Logging it"],
    ["DeepSeek's older section tokens", `ok <${BAR}tool▁calls▁begin${BAR}>junk<${BAR}tool▁calls▁end${BAR}> bye`, "ok  bye"],
    ["a harmony tool call", 'Checking.<|start|>assistant<|channel|>commentary to=functions.fuel <|constrain|>json<|message|>{"q":1}<|call|>', "Checking."],
    ["a harmony final answer", "<|channel|>final<|message|>The total is Rs 14,000.<|return|>", "The total is Rs 14,000."],
    ["Qwen-style XML", 'Logging. <tool_call>\n{"name": "fuel", "arguments": {"a": 1}}\n</tool_call>', "Logging."],
    ["Anthropic-style XML", 'x <function_calls><invoke name="fuel"><parameter name="a">1</parameter></invoke></function_calls> y', "x  y"],
    ["a Llama function tag", 'go <function=fuel>{"a": 1}</function> end', "go  end"],
    ["a bare JSON call", 'Here you go: {"name": "fuel", "arguments": {"query_entity": "fuel_logs", "n": {"deep": [1, 2]}}}', "Here you go:"],
    ["a list of JSON calls", '[{"name":"a","arguments":{}},{"name":"b","arguments":{"x":1}}] ok', "ok"],
    ["a fenced JSON call", 'Doing it.\n```json\n{"tool": "fuel", "args": {"q": 1}}\n```\n', "Doing it."],
    ["an OpenAI-shaped call", '{"type": "function", "function": {"name": "fuel", "arguments": "{}"}}', ""],
  ])("removes %s", (_label, input, expected) => {
    expect(stripToolMarkup(input)).toBe(expected)
    expect(hasToolMarkup(input)).toBe(true)
  })

  it.each([
    "Total fuel: 155 Liters | Cost: Rs 43,500",
    "| Vehicle | Liters |\n|---|---|\n| AB-1234 | 50 |",
    'The API returns {"status": "ok", "count": 3}.',
    'Vehicle record: {"name": "Toyota Hilux", "year": 2022}',
    "Use the <b>bold</b> tag or a list [1, 2, 3].",
    "We invoke the brakes; the function of this part is to stop.",
    "**Fuel & Cost Summary for Vehicle AB-1234**\n* **Total Fuel Consumed:** 155 Liters",
    "5 < 6 and 7 > 3, or a | b",
    "",
  ])("leaves ordinary text untouched: %j", (input) => {
    expect(stripToolMarkup(input)).toBe(input)
    expect(hasToolMarkup(input)).toBe(false)
  })

  it("is idempotent", () => {
    const once = stripToolMarkup(`Hello ${REPORTED} world`)
    expect(stripToolMarkup(once)).toBe(once)
    expect(once).toBe("Hello  world")
  })

  it("survives JSON with braces and escaped quotes inside strings", () => {
    const text = 'Before {"name": "fuel", "arguments": {"note": "a } tricky \\" string {"}} after'
    expect(stripToolMarkup(text)).toBe("Before  after")
  })
})
