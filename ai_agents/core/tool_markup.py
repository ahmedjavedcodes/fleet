"""Raw model tool-call markup: recognised, and removed, before it can reach a user.

Some hosted models answer a tool request with their *native* call syntax as ordinary text instead of a
structured tool call -- DeepSeek's `<｜DSML｜tool_calls><｜DSML｜invoke name="fuel">...`, gpt-oss's harmony
tokens, Qwen/Hermes `<tool_call>`, Anthropic-style `<function_calls><invoke>`, Llama's `<function=...>`, or a bare
`{"name": ..., "arguments": {...}}`. None of it is an answer. It is shown nowhere, stored nowhere and never fed
back to a model as history:

  * core.llm_failover treats a reply containing it as a failed attempt and moves to the next model;
  * orchestrator.sanitize_output removes it from synthesized text;
  * orchestrator.session strips it from the final response before it is saved or streamed, and from stored
    history when a conversation is resumed.

The frontend has a matching safeguard (src/lib/sanitize-message.ts). Keep the two in step.

Deliberately conservative: only constructs that cannot be ordinary prose are touched. Plain text, Markdown,
tables, numbers and JSON that is not shaped like a tool call pass through byte for byte.
"""

from __future__ import annotations

import html
import json
import re
import uuid

# The ASCII bar and the fullwidth bar (U+FF5C) that DeepSeek's special tokens are written with.
_BAR = "[|｜]"
_S = re.DOTALL | re.IGNORECASE

# DeepSeek DSML: <｜DSML｜tool_calls> <｜DSML｜invoke name="x"> <｜DSML｜parameter name="y">v</｜DSML｜parameter> ...
_DSML_CALLS = re.compile(rf"<{_BAR}\s*DSML\s*{_BAR}\s*(tool_calls?|function_calls?)\s*>.*?</{_BAR}\s*DSML\s*{_BAR}\s*\1\s*>", _S)
_DSML_CALLS_OPEN = re.compile(rf"<{_BAR}\s*DSML\s*{_BAR}\s*(?:tool_calls?|function_calls?)\b.*\Z", _S)
_DSML_INNER = re.compile(rf"<{_BAR}\s*DSML\s*{_BAR}\s*(invoke|parameter)\b[^>]*>.*?</{_BAR}\s*DSML\s*{_BAR}\s*\1\s*>", _S)
_DSML_TAG = re.compile(rf"</?{_BAR}\s*DSML\s*{_BAR}[^<>]*>", _S)

# DeepSeek's older section tokens: <｜tool▁calls▁begin｜> ... <｜tool▁calls▁end｜>
_TOKEN_CALLS = re.compile(rf"<{_BAR}\s*tool[▁_ ]calls?[▁_ ]begin\s*{_BAR}>.*?(?:<{_BAR}\s*tool[▁_ ]calls?[▁_ ]end\s*{_BAR}>|\Z)", _S)

# gpt-oss "harmony": a call addressed to a tool (`to=functions.x`) and the hidden analysis channel are dropped whole;
# the final channel is an answer, so only its tokens go (see _SPECIAL_TOKEN).
_HARMONY_HEADER = r"(?:[^<]|<\|constrain\|>)*?"  # header text, which may contain a <|constrain|> token
_HARMONY_CALL = re.compile(
    rf"(?:<\|start\|>(?:assistant|system|user|developer)?)?<\|channel\|>{_HARMONY_HEADER}\bto={_HARMONY_HEADER}<\|message\|>.*?(?:<\|call\|>|\Z)", _S
)
_HARMONY_ANALYSIS = re.compile(r"<\|channel\|>\s*analysis\s*<\|message\|>.*?(?:<\|end\|>|\Z)", _S)
_HARMONY_HEAD = re.compile(
    r"(?:<\|start\|>(?:assistant|system|user|developer)?)?<\|channel\|>\s*(?:final|commentary)\s*(?:<\|constrain\|>\s*\w+\s*)?<\|message\|>", _S
)
_HARMONY_ROLE = re.compile(r"<\|start\|>(?:assistant|system|user|developer)\b", _S)

# Any remaining chat-template token: <|channel|>, <|im_start|>, <｜end▁of▁sentence｜> ...
_SPECIAL_TOKEN = re.compile(rf"<{_BAR}[^<>|｜\n]{{1,48}}{_BAR}>")

# XML-style calls: Qwen/Hermes <tool_call>, Anthropic-style <function_calls><invoke>, <tool_use>, <tool_code>.
_XML_BLOCK = re.compile(r"<(tool_calls?|function_calls?|tool_use|tool_code|tool_results?|function_results?|invoke)\b[^>]*>.*?</\1\s*>", _S)
_XML_OPEN = re.compile(r"<(?:tool_calls?|function_calls?|tool_use|tool_code)\b[^>]*>.*\Z", _S)
_XML_STRAY = re.compile(r"</?(?:tool_calls?|function_calls?|tool_use|tool_code|tool_results?|function_results?|invoke|parameter)\b[^>]*>", re.IGNORECASE)
_LLAMA_FUNCTION = re.compile(r"<function=[\w.\-]+>.*?</function>", _S)

_EMPTY_FENCE = re.compile(r"```[a-z]*\s*```", re.IGNORECASE)

# A JSON object/array shaped like a tool call: {"name": "fuel", "arguments": {...}}.
_NAME_KEYS = frozenset({"name", "tool", "tool_name", "function", "function_name", "recipient_name"})
_ARG_KEYS = frozenset({"arguments", "args", "parameters", "params", "input", "tool_input"})
_ENVELOPE_KEYS = frozenset({"id", "type", "index"})
_DECODER = json.JSONDecoder()


def _is_tool_call(value: object) -> bool:
    if isinstance(value, list):
        return bool(value) and all(_is_tool_call(item) for item in value)
    if not isinstance(value, dict):
        return False
    if isinstance(value.get("tool_calls"), list):
        return True
    if isinstance(value.get("function"), dict):  # OpenAI: {"type": "function", "function": {"name": ..., "arguments": ...}}
        return _is_tool_call(value["function"])
    keys = set(value)
    names = [value[k] for k in keys & _NAME_KEYS]
    return bool(names) and all(isinstance(n, str) for n in names) and bool(keys & _ARG_KEYS) and keys <= (_NAME_KEYS | _ARG_KEYS | _ENVELOPE_KEYS)


def _strip_json_calls(text: str) -> str:
    if "{" not in text and "[" not in text:
        return text
    out: list[str] = []
    i = 0
    while i < len(text):
        char = text[i]
        if char in "{[" and text[i + 1 : i + 40].lstrip()[:1] in ('"', "{"):
            try:
                value, end = _DECODER.raw_decode(text, i)
            except ValueError:
                value = end = None
            if end is not None and _is_tool_call(value):
                i = end
                continue
        out.append(char)
        i += 1
    return "".join(out)


def _tidy(text: str) -> str:
    text = re.sub(r"[ \t]+\n", "\n", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def strip_tool_markup(text: str) -> str:
    """`text` with every raw tool-call construct removed, or `text` itself, untouched, if it has none.
    Whitespace is only tidied when something was actually removed."""
    if not text:
        return text
    cleaned = text
    for pattern in (
        _DSML_CALLS, _DSML_CALLS_OPEN, _DSML_INNER, _DSML_TAG, _TOKEN_CALLS, _HARMONY_CALL, _HARMONY_ANALYSIS,
        _HARMONY_HEAD, _HARMONY_ROLE, _SPECIAL_TOKEN, _XML_BLOCK, _XML_OPEN, _LLAMA_FUNCTION, _XML_STRAY,
    ):
        cleaned = pattern.sub("", cleaned)
    cleaned = _strip_json_calls(cleaned)
    if cleaned == text:
        return text
    return _tidy(_EMPTY_FENCE.sub("", cleaned))


def has_tool_markup(text: str) -> bool:
    return bool(text) and strip_tool_markup(text) != text


# --- recovering the call the model meant to make ----------------------------------------------------------------

# <｜DSML｜invoke name="fuel"> <｜DSML｜parameter name="fuel_fields" string="false">{"liters_filled": 50}</｜DSML｜parameter> ...
_DSML_INVOKE = re.compile(rf'<{_BAR}\s*DSML\s*{_BAR}\s*invoke\s+name="([^"]+)"\s*>(.*?)</{_BAR}\s*DSML\s*{_BAR}\s*invoke\s*>', _S)
_DSML_PARAMETER = re.compile(
    rf'<{_BAR}\s*DSML\s*{_BAR}\s*parameter\s+name="([^"]+)"(?:\s+string="(true|false)")?\s*>(.*?)</{_BAR}\s*DSML\s*{_BAR}\s*parameter\s*>', _S
)
_XML_TOOL_CALL = re.compile(r"<tool_call>\s*(.*?)\s*</tool_call>", _S)


def recover_tool_calls(text: str) -> list[dict]:
    """The tool calls a model wrote out as raw text instead of making them properly, as LangChain tool-call dicts.

    Understands DeepSeek's DSML (string="false" parameters carry JSON, so nested objects and numbers survive) and
    the Qwen/Hermes `<tool_call>{"name": ..., "arguments": {...}}</tool_call>` form. Anything it cannot read
    cleanly is left out, never guessed. The caller still validates the arguments like any other tool call."""
    if not text:
        return []
    calls: list[dict] = []
    for name, body in _DSML_INVOKE.findall(text):
        args: dict = {}
        for key, is_string, raw in _DSML_PARAMETER.findall(body):
            value: object = html.unescape(raw.strip())
            if is_string == "false":
                try:
                    value = json.loads(str(value))
                except ValueError:
                    pass
            args[key] = value
        calls.append({"name": name, "args": args, "id": f"call_{uuid.uuid4().hex[:16]}", "type": "tool_call"})
    for body in _XML_TOOL_CALL.findall(text):
        try:
            payload = json.loads(body)
        except ValueError:
            continue
        if isinstance(payload, dict) and isinstance(payload.get("name"), str):
            args = payload.get("arguments", payload.get("parameters", {}))
            if isinstance(args, str):
                try:
                    args = json.loads(args)
                except ValueError:
                    continue
            if isinstance(args, dict):
                calls.append({"name": payload["name"], "args": args, "id": f"call_{uuid.uuid4().hex[:16]}", "type": "tool_call"})
    return calls
