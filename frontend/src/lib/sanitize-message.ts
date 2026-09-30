// Last-resort safeguard for assistant text. The chat server never sends raw model tool-call markup (see
// ai_agents/core/tool_markup.py, which this mirrors), but a model that prints its native call syntax as ordinary
// text -- DeepSeek's <｜DSML｜tool_calls>, <tool_call> XML, gpt-oss harmony tokens, a bare {"name", "arguments"}
// object -- must never be shown to a person even if an older server, a stored transcript or a future provider lets
// it through. Only constructs that cannot be ordinary prose are touched; everything else is returned unchanged.

// The ASCII bar and the fullwidth bar (U+FF5C) DeepSeek's special tokens are written with.
const BAR = "[|\\uFF5C]"
const DSML = `<${BAR}\\s*DSML\\s*${BAR}\\s*`
const DSML_CLOSE = `</${BAR}\\s*DSML\\s*${BAR}\\s*`

// Whole blocks first, then whatever is left of them. Order matters: a block's tags must not be stripped one by
// one while their contents stay behind.
const BLOCK_PATTERNS: RegExp[] = [
  // DeepSeek DSML: <｜DSML｜tool_calls> <｜DSML｜invoke name="x"> <｜DSML｜parameter name="y">v</｜DSML｜parameter> ...
  new RegExp(`${DSML}(tool_calls?|function_calls?)\\s*>[\\s\\S]*?${DSML_CLOSE}\\1\\s*>`, "gi"),
  new RegExp(`${DSML}(?:tool_calls?|function_calls?)\\b[\\s\\S]*$`, "i"), // a call cut off mid-way
  new RegExp(`${DSML}(invoke|parameter)\\b[^>]*>[\\s\\S]*?${DSML_CLOSE}\\1\\s*>`, "gi"),
  new RegExp(`</?${BAR}\\s*DSML\\s*${BAR}[^<>]*>`, "gi"),
  // DeepSeek's older section tokens.
  new RegExp(`<${BAR}\\s*tool[\\u2581_ ]calls?[\\u2581_ ]begin\\s*${BAR}>[\\s\\S]*?(?:<${BAR}\\s*tool[\\u2581_ ]calls?[\\u2581_ ]end\\s*${BAR}>|$)`, "gi"),
  // gpt-oss harmony: a call addressed to a tool (to=functions.x) and the hidden analysis channel go whole; the
  // final channel is an answer, so only its tokens are removed below.
  /(?:<\|start\|>(?:assistant|system|user|developer)?)?<\|channel\|>(?:[^<]|<\|constrain\|>)*?\bto=(?:[^<]|<\|constrain\|>)*<\|message\|>[\s\S]*?(?:<\|call\|>|$)/gi,
  /<\|channel\|>\s*analysis\s*<\|message\|>[\s\S]*?(?:<\|end\|>|$)/gi,
  /(?:<\|start\|>(?:assistant|system|user|developer)?)?<\|channel\|>\s*(?:final|commentary)\s*(?:<\|constrain\|>\s*\w+\s*)?<\|message\|>/gi,
  /<\|start\|>(?:assistant|system|user|developer)\b/gi,
  // Any remaining chat-template token, and one still arriving (a stream can end mid-token).
  new RegExp(`<${BAR}[^<>|\\uFF5C\\n]{1,48}${BAR}>`, "g"),
  new RegExp(`<${BAR}[^<>\\n]{0,48}$`),
  // XML-style calls: Qwen/Hermes <tool_call>, Anthropic-style <function_calls><invoke>, <tool_use>, <tool_code>.
  /<(tool_calls?|function_calls?|tool_use|tool_code|tool_results?|function_results?|invoke)\b[^>]*>[\s\S]*?<\/\1\s*>/gi,
  /<(?:tool_calls?|function_calls?|tool_use|tool_code)\b[^>]*>[\s\S]*$/i,
  /<function=[\w.-]+>[\s\S]*?<\/function>/gi,
  /<\/?(?:tool_calls?|function_calls?|tool_use|tool_code|tool_results?|function_results?|invoke|parameter)\b[^>]*>/gi,
]

const NAME_KEYS = new Set(["name", "tool", "tool_name", "function", "function_name", "recipient_name"])
const ARG_KEYS = new Set(["arguments", "args", "parameters", "params", "input", "tool_input"])
const ENVELOPE_KEYS = new Set(["id", "type", "index"])

function isToolCall(value: unknown): boolean {
  if (Array.isArray(value)) return value.length > 0 && value.every(isToolCall)
  if (value === null || typeof value !== "object") return false
  const record = value as Record<string, unknown>
  if (Array.isArray(record.tool_calls)) return true
  if (record.function !== null && typeof record.function === "object" && !Array.isArray(record.function)) return isToolCall(record.function)
  const keys = Object.keys(record)
  const names = keys.filter((k) => NAME_KEYS.has(k))
  return (
    names.length > 0 &&
    names.every((k) => typeof record[k] === "string") &&
    keys.some((k) => ARG_KEYS.has(k)) &&
    keys.every((k) => NAME_KEYS.has(k) || ARG_KEYS.has(k) || ENVELOPE_KEYS.has(k))
  )
}

/** Index just past the JSON object/array starting at `start`, or -1 if it never closes. */
function balancedEnd(text: string, start: number): number {
  let depth = 0
  let inString = false
  let escaped = false
  for (let i = start; i < text.length; i++) {
    const c = text[i]
    if (inString) {
      if (escaped) escaped = false
      else if (c === "\\") escaped = true
      else if (c === '"') inString = false
      continue
    }
    if (c === '"') inString = true
    else if (c === "{" || c === "[") depth++
    else if (c === "}" || c === "]") {
      depth--
      if (depth === 0) return i + 1
    }
  }
  return -1
}

function stripJsonToolCalls(text: string): string {
  if (!text.includes("{") && !text.includes("[")) return text
  let out = ""
  let i = 0
  while (i < text.length) {
    const c = text[i]
    if ((c === "{" || c === "[") && /^\s*["{]/.test(text.slice(i + 1, i + 40))) {
      const end = balancedEnd(text, i)
      if (end !== -1) {
        let parsed: unknown
        try {
          parsed = JSON.parse(text.slice(i, end))
        } catch {
          parsed = undefined
        }
        if (isToolCall(parsed)) {
          i = end
          continue
        }
      }
    }
    out += c
    i++
  }
  return out
}

/** `text` with every raw tool-call construct removed, or `text` itself if it has none. */
export function stripToolMarkup(text: string): string {
  if (!text) return text
  let cleaned = text
  for (const pattern of BLOCK_PATTERNS) cleaned = cleaned.replace(pattern, "")
  cleaned = stripJsonToolCalls(cleaned)
  if (cleaned === text) return text
  return cleaned
    .replace(/```[a-z]*\s*```/gi, "")
    .replace(/[ \t]+\n/g, "\n")
    .replace(/\n{3,}/g, "\n\n")
    .trim()
}

export function hasToolMarkup(text: string): boolean {
  return Boolean(text) && stripToolMarkup(text) !== text
}
