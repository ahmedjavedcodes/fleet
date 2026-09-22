"""Builds the six LangChain tool definitions the routing LLM binds to.

Per grand-orchestrator.md FR 1: the six compiled sub-agent LangGraphs are
exposed as deterministic tools. Each StructuredTool's `func` is a stub --
the orchestrator graph (graph.py's execute_tool node) intercepts the LLM's
tool_calls and dispatches to SubAgentRunner itself, rather than letting
LangChain invoke the tool function directly, since dispatch needs the
session's shared SubAgentRunner/auth_context/scratchpad, not just the raw
tool arguments.
"""

from __future__ import annotations

from typing import Any

from langchain_core.tools import StructuredTool

from orchestrator.registry import SUB_AGENT_REGISTRY
from orchestrator.tool_schemas import TOOL_SCHEMAS


def _undispatched(**kwargs: Any) -> None:
    raise NotImplementedError("Tool calls are intercepted and dispatched by the orchestrator graph, never invoked directly.")


def build_llm_tools() -> list[StructuredTool]:
    tools = []
    for name, spec in SUB_AGENT_REGISTRY.items():
        schema = TOOL_SCHEMAS[name]
        field_guidance = (schema.__doc__ or "").strip()
        description = f"{spec.description}\n\n{field_guidance}" if field_guidance else spec.description
        tools.append(StructuredTool.from_function(func=_undispatched, name=name, description=description, args_schema=schema))
    return tools
