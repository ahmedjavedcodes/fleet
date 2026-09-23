"""Input security & guardrail pre-hook, per execution-pre_hooks.md §2.

Runs in OrchestratorSession.run(), before anything is pushed to the graph
-- a violation short-circuits the whole turn without invoking the LLM at
all (AC 1: "without calling Groq").

Correction against the spec's own example: AC 1's sample text is "ignore
all previous instructions", but the spec's own SecurityConfig.blocked_phrases
default is the literal substring "ignore previous" -- which does NOT occur
in that sentence ("all" sits between the two words), so a naive substring
check would fail the spec's own acceptance test. Regex patterns tolerant of
words in between (ignore\\s+(all\\s+)?...previous...instructions) are the
primary detection mechanism; blocked_phrases remains as a literal
supplementary layer, exactly as specced, for phrases where substring
matching is what's actually wanted (e.g. "drop table").
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from pydantic import BaseModel


class SecurityConfig(BaseModel):
    max_input_length: int = 1000
    blocked_phrases: frozenset[str] = frozenset({"ignore previous", "system prompt", "bypass", "drop table"})
    enable_llm_guard: bool = False  # Toggle for an optional, lightweight dedicated guard model -- not implemented; see module docstring in graph.py's security integration


DEFAULT_SECURITY_CONFIG = SecurityConfig()

OFF_TOPIC_MESSAGE = "I can only help with fleet operations, HR, maintenance, or logistics questions. Please rephrase your request."
INJECTION_MESSAGE = "I can't process that request."

# Tolerant of words in between ("ignore ALL previous", "please DISREGARD the
# prior instructions") -- a plain substring check misses the spec's own AC 1
# example, see module docstring.
_INJECTION_PATTERNS = [
    re.compile(r"ignore\s+(all\s+|any\s+)?(the\s+)?(previous|prior|above|earlier)\s+instructions?", re.IGNORECASE),
    re.compile(r"disregard\s+(all\s+|any\s+)?(the\s+)?(previous|prior|above|earlier)\s+instructions?", re.IGNORECASE),
    re.compile(r"you\s+are\s+now\s+\w", re.IGNORECASE),
    re.compile(r"reveal\s+(your\s+)?(system\s+)?prompt", re.IGNORECASE),
    re.compile(r"\bdrop\s+table\b", re.IGNORECASE),
]

# Domain-bounding: a lightweight allowlist heuristic -- no LLM call, matching
# SecurityConfig.enable_llm_guard's default of False. Deliberately broad
# (spans every sub-agent's domain) so a real fleet question essentially
# never false-positives; this can only reject with confidence, not confirm.
_DOMAIN_KEYWORDS = frozenset({
    "vehicle", "vehicles", "car", "cars", "truck", "trucks", "fleet", "plate",
    "driver", "drivers", "license", "assign", "assignment", "custody", "pairing",
    "fuel", "gas", "petrol", "diesel", "receipt", "trip", "odometer", "mileage",
    "maintenance", "repair", "service", "inventory", "part", "parts", "stock", "restock",
    "invoice", "work order",
    "incident", "accident", "safety", "violation", "damage",
    "dashboard", "summary", "insight", "insights", "health", "trend", "trends",
    "cost", "expense", "report", "budget",
    "hr", "human resources", "logistics", "shift", "roster", "employee", "staff",
})


@dataclass(frozen=True)
class SecurityViolation:
    reason: str
    rejection_message: str


def scan_user_input(text: str, *, config: SecurityConfig = DEFAULT_SECURITY_CONFIG) -> SecurityViolation | None:
    """Returns a SecurityViolation if `text` should be rejected before
    reaching the LLM, else None. Pure regex/string heuristics -- no LLM
    call is made here, matching config.enable_llm_guard's default of False.
    """
    if not text or not text.strip():
        return SecurityViolation(reason="Empty input.", rejection_message=INJECTION_MESSAGE)

    if len(text) > config.max_input_length:
        return SecurityViolation(
            reason=f"Input exceeds max_input_length ({config.max_input_length} chars).",
            rejection_message=INJECTION_MESSAGE,
        )

    lowered = text.lower()

    for phrase in config.blocked_phrases:
        if phrase in lowered:
            return SecurityViolation(reason=f"Blocked phrase detected: {phrase!r}.", rejection_message=INJECTION_MESSAGE)

    for pattern in _INJECTION_PATTERNS:
        if pattern.search(text):
            return SecurityViolation(reason=f"Injection pattern matched: {pattern.pattern!r}.", rejection_message=INJECTION_MESSAGE)

    if not any(keyword in lowered for keyword in _DOMAIN_KEYWORDS):
        return SecurityViolation(reason="No fleet/HR/maintenance/logistics domain keyword found.", rejection_message=OFF_TOPIC_MESSAGE)

    return None
