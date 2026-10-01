"""Keeps what is sent to the model small: tool results, and old conversation turns.

Every planning call re-sends the whole conversation so far, so a bulky tool result is paid for again on every later
call of the turn. Results are compacted (empty fields and bookkeeping dropped) and capped; old turns are shortened.
"""

from __future__ import annotations

import json
from typing import Any

CHARS_PER_TOKEN = 3.5  # a deliberately cautious estimate for English and JSON-ish text
OBSERVATION_MAX_TOKENS = 800
OLD_TURN_MAX_CHARS = 700

# Bookkeeping that never answers a question.
_NOISE_KEYS = frozenset({"created_at", "updated_at", "organization_id", "is_deleted", "content_sha256", "uploaded_by"})


def compact(value: Any) -> Any:
    """`value` without empty fields (None, "", [], {}) and bookkeeping keys, recursively."""
    if isinstance(value, dict):
        return {k: compact(v) for k, v in value.items() if k not in _NOISE_KEYS and v not in (None, "", [], {})}
    if isinstance(value, (list, tuple)):
        return [compact(v) for v in value]
    return value


def cap_text(text: str, max_tokens: int = OBSERVATION_MAX_TOKENS) -> str:
    limit = int(max_tokens * CHARS_PER_TOKEN)
    if len(text) <= limit:
        return text
    return f"{text[:limit]} ...[cut: {len(text) - limit} more characters; narrow the request if they are needed]"


def render_result(key: str, value: Any, max_tokens: int = OBSERVATION_MAX_TOKENS) -> str:
    """`key=<value>` for a tool result, compacted and within budget. A list of records is cut between records, with a
    count of what was left out, so the model never reads half a record."""
    value = compact(value)
    if isinstance(value, list) and value and all(isinstance(v, dict) for v in value):
        limit = int(max_tokens * CHARS_PER_TOKEN)
        kept: list[str] = []
        used = 0
        for record in value:
            text = json.dumps(record, default=str, ensure_ascii=False, separators=(",", ":"))
            if kept and used + len(text) > limit:
                break
            kept.append(text)
            used += len(text) + 1
        omitted = len(value) - len(kept)
        body = "[" + ",".join(kept) + "]"
        if omitted:
            body += f" ...[{omitted} more of {len(value)} records not shown; filter the request (e.g. one plate) to see them]"
        return f"{key}={body}"
    text = json.dumps(value, default=str, ensure_ascii=False, separators=(",", ":")) if isinstance(value, (dict, list)) else repr(value)
    return f"{key}={cap_text(text, max_tokens)}"


def shorten_turn(text: str, max_chars: int = OLD_TURN_MAX_CHARS) -> str:
    """An earlier conversation turn, cut down: the model needs the gist of it, not every word."""
    if len(text) <= max_chars:
        return text
    return text[:max_chars].rstrip() + " ...[earlier message shortened]"
