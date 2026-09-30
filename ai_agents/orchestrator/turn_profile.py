"""Cheap, deterministic turn classification for the latency fast path.

Decides BEFORE the planner runs whether a turn is a plain read ("how many
vehicles are overdue?", "show fuel trends") so fetch_memory can avoid blocking
the planner on long-term (semantic) recall. No LLM call: a regex pass costs
microseconds, and an extra classifier round-trip would eat the saving.

Deliberately conservative. Only a message that looks like a question or
lookup AND contains no write/memory verb AND carries no attachment is a read;
anything else takes the full path. A misclassified write loses nothing
important -- writes are gated structurally by each sub-agent and HITL, not by
this label -- and the truth-checker decision is made from what the turn
actually executed (see graph.py's fact_check), not from this guess.
"""

from __future__ import annotations

import re
from typing import Literal

TurnKind = Literal["read", "full"]

_WRITE_OR_MEMORY = re.compile(
    r"\b("
    r"log|logged|logging|add|adding|create|record|register|onboard|assign|reassign|unassign|release|"
    r"update|change|edit|set|mark|resolve|close|delete|remove|cancel|file|report(?:ing)?\s+(?:an?\s+)?incident|"
    r"restock|receive[ds]?|order|approve|reject|upload|attach(?:ed)?|"
    r"remember|forget|note\s+that|save|always|never|prefer|from\s+now\s+on"
    r")\b",
    re.IGNORECASE,
)

_READ_LEAD = re.compile(
    r"^\s*(?:please\s+|can\s+you\s+|could\s+you\s+)?("
    r"what|what's|whats|which|who|whose|when|where|why|how|is|are|was|were|does|do|did|has|have|"
    r"show|list|display|get|give\s+me|tell\s+me|find|check|compare|summari[sz]e|count|view|see"
    r")\b",
    re.IGNORECASE,
)


def classify_turn(message: str, *, has_attachment: bool = False) -> TurnKind:
    if has_attachment or not message:
        return "full"
    if _WRITE_OR_MEMORY.search(message):
        return "full"
    return "read" if _READ_LEAD.search(message) else "full"
