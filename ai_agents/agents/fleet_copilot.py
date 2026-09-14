"""FleetCopilot: the top-level LangGraph orchestrator.

Wires together conversational buffer memory (short-term) and Pinecone
vector memory (long-term, see ai_agents/memory) around a multi-provider
LLM, per the agent architecture in CLAUDE.md.
"""

from __future__ import annotations

from typing import Annotated, TypedDict

from langgraph.graph import END, StateGraph
from langgraph.graph.message import add_messages


class FleetCopilotState(TypedDict):
    messages: Annotated[list, add_messages]


def respond(state: FleetCopilotState) -> FleetCopilotState:
    """Placeholder node, replaced by the real LLM call once a provider is wired in."""
    return state


def build_graph() -> StateGraph:
    graph = StateGraph(FleetCopilotState)
    graph.add_node("respond", respond)
    graph.set_entry_point("respond")
    graph.add_edge("respond", END)
    return graph


def get_compiled_graph():
    return build_graph().compile()
