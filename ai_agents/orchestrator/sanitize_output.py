"""Last line of defence against model "thinking out loud" reaching the user.

Prompts tell the model not to show its reasoning, but some hosted models still leak it: a
<think> block, a raw record ({'plate_number': 'AB-1234'}), or a self-correction ("wait, let me
re-examine ... Yes, that is indeed the plate."). This strips those from the final reply.

Deliberately conservative: it removes whole *sentences* that are unmistakably monologue and
leaves everything else -- numbers, tables, bold text, bullets -- untouched. If cleaning would
leave nothing, the lightly cleaned text (tags and raw records only) is returned instead of an
empty reply. `sanitize_response` also reports whether anything was found so the caller can
regenerate once with a stricter instruction.
"""

from __future__ import annotations

import re
from typing import NamedTuple

from core.tool_markup import strip_tool_markup

_THINK_BLOCK = re.compile(r"<(think|thinking|reasoning|analysis|scratchpad)>.*?</\1>", re.S | re.I)
_UNCLOSED_THINK = re.compile(r"<(think|thinking|reasoning|analysis|scratchpad)>.*\Z", re.S | re.I)
_STRAY_TAG = re.compile(r"</?(think|thinking|reasoning|analysis|scratchpad)>", re.I)
_HARMONY = re.compile(r"<\|[a-z_]+\|>")
_FENCED_JSON = re.compile(r"```(?:json|python)?\s*[\[{].*?```", re.S | re.I)
# A single-level dict/JSON object with quoted keys, e.g. {'plate_number': 'AB-1234', 'year': 2022}.
_RECORD_BLOB = re.compile(r"\{[^{}]*['\"][\w .-]+['\"]\s*:[^{}]*\}")
# A list of such records: [{...}, {...}] (after the blobs inside were removed it is just [, ]).
_EMPTY_LIST = re.compile(r"\[\s*(?:,\s*)*\]")

_MONOLOGUE = re.compile(
    r"\b(?:"
    r"wait\s*[,.…!:—-]"                       # "wait, ..." (not "waiting for parts")
    r"|hold on\s*[,.…]"
    r"|hmm+\s*[,.…]"
    r"|let me (?:re-?examine|re-?check|double[- ]check|look (?:again|at)|re-?read|re-?think|reconsider|verify|check again|recompute|recalculate|see|think)"
    r"|on second thought"
    r"|(?:i|we) (?:need|should|must) (?:to )?(?:re-?examine|re-?check|double[- ]check|re-?read|verify)"
    r"|looking at (?:the )?(?:query|tool|returned|search|function|api) (?:results?|output|observations?|responses?)"
    r"|(?:the|this) (?:tool )?(?:output|result|observation)s? (?:shows?|says?|returns?|indicates?)\s*[:{]"
    r"|actually,? (?:that|it|no|the (?:output|result|data))"
    r")",
    re.I,
)
# Self-answering leftovers: "Yes, that is indeed the plate." right after a dropped self-correction.
_SELF_CONFIRM = re.compile(r"^(?:yes|no|okay|ok|right|so|indeed|correct)\b[,.!]?\s", re.I)
_SENTENCE_SPLIT = re.compile(r"(?<=[.!?…])\s+")


class Sanitized(NamedTuple):
    text: str
    leaked: bool  # something reasoning-like or raw was found (and removed)


def _light_clean(text: str) -> str:
    text = strip_tool_markup(text)  # raw tool-call syntax (DSML, <tool_call>, harmony, bare JSON calls)
    text = _THINK_BLOCK.sub("", text)
    text = _UNCLOSED_THINK.sub("", text)
    text = _STRAY_TAG.sub("", text)
    text = _HARMONY.sub("", text)
    text = _FENCED_JSON.sub("", text)
    text = _RECORD_BLOB.sub("", text)
    text = _EMPTY_LIST.sub("", text)
    return text


def _drop_monologue(text: str) -> str:
    kept_lines: list[str] = []
    for line in text.split("\n"):
        if not line.strip():
            kept_lines.append(line)
            continue
        sentences = _SENTENCE_SPLIT.split(line)
        kept: list[str] = []
        previous_dropped = False
        for sentence in sentences:
            drop = bool(_MONOLOGUE.search(sentence)) or (previous_dropped and bool(_SELF_CONFIRM.match(sentence)))
            previous_dropped = drop
            if not drop:
                kept.append(sentence)
        if kept:
            kept_lines.append(" ".join(kept))
    return "\n".join(kept_lines)


def _tidy(text: str) -> str:
    text = re.sub(r"[ \t]+\n", "\n", text)
    text = re.sub(r"[ \t]{2,}", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def sanitize_response(text: str) -> Sanitized:
    if not text:
        return Sanitized(text or "", False)
    light = _light_clean(text)
    full = _drop_monologue(light)
    leaked = _tidy(full) != _tidy(text)
    # If cleaning leaves nothing, every sentence was monologue: return empty (never the raw text)
    # so the caller regenerates instead of showing it.
    return Sanitized(_tidy(full), leaked)


def clean_response(text: str) -> str:
    return sanitize_response(text).text
