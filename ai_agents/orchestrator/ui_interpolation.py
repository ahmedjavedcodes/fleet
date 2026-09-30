"""Zero-cost UI status-string interpolation, per fleet-live-observer.md §4.

Pure Python string interpolation over an already-validated tool-call args
dict -- never an LLM call (FR 2 / AC 4). Every mapping falls back to a
generic string when its expected arg is missing, per the spec's "falls
back to a safe generic string" rule.
"""

from __future__ import annotations

from typing import Any

NODE_MESSAGES = {
    "plan": "Thinking and planning next steps...",
    "synthesize": "Drafting final response...",
}

HITL_PAUSE_MESSAGE = "Action paused: Waiting for your approval."

_GENERIC_TOOL_MESSAGE = "Working on it..."


def interpolate_node(node_name: str) -> str:
    return NODE_MESSAGES.get(node_name, _GENERIC_TOOL_MESSAGE)


def interpolate_tool_start(tool_name: str, args: dict[str, Any]) -> str:
    args = args or {}
    if tool_name == "assignment":
        return f"Checking assignment rules for {args.get('query_vehicle_id', 'vehicle')}..."
    if tool_name == "foundation":
        return f"Searching fleet registry for {args.get('query_entity', 'records')}..."
    if tool_name == "fuel":
        if args.get("trip_fields"):
            return "Logging the trip..."
        if args.get("fuel_fields") or args.get("document_type"):
            return "Recording the fuel log..."
        return "Auditing fuel and trip logs..."
    if tool_name == "maintenance":
        return f"Verifying maintenance inventory for {args.get('query_entity', 'parts')}..."
    if tool_name == "accountability":
        if args.get("document_type"):
            return "Filing the incident report..."
        return "Reviewing incidents and driver accountability..."
    if tool_name == "insights":
        return "Pulling strategic insights..."
    if tool_name == "search_documents":
        return "Searching uploaded documents..."
    if tool_name == "update_memory":
        return "Preparing a note to remember..."
    return _GENERIC_TOOL_MESSAGE
