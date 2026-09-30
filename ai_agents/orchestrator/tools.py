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
from orchestrator.tool_schemas import DOCUMENT_TOOL_NAME, MEMORY_TOOL_NAME, TOOL_SCHEMAS, SearchDocumentsInput, UpdateMemoryInput


def compact_schema(node: Any) -> Any:
    """The same JSON schema without Pydantic's boilerplate: per-property "title"s, null
    defaults and "anyOf [X, null]" wrappers. Roughly a third fewer tokens per tool on every
    single LLM call. Only what the model *sees* is compacted: arguments are still validated
    against the real Pydantic models (orchestrator/retry.py), so nothing is loosened."""
    if isinstance(node, list):
        return [compact_schema(x) for x in node]
    if not isinstance(node, dict):
        return node
    any_of = node.get("anyOf")
    if any_of and len(any_of) == 2 and {"type": "null"} in any_of:
        other = compact_schema(next(x for x in any_of if x != {"type": "null"}))
        node = {**{k: v for k, v in node.items() if k != "anyOf"}, **other}
    return {k: compact_schema(v) for k, v in node.items() if k != "title" and not (k == "default" and v is None)}


def _undispatched(**kwargs: Any) -> None:
    raise NotImplementedError("Tool calls are intercepted and dispatched by the orchestrator graph, never invoked directly.")


def build_llm_tools(*, include_memory: bool = False, include_documents: bool = False) -> list[StructuredTool]:
    """include_memory adds update_memory -- only offered when the session
    actually has agent memory configured, so the LLM never proposes a save
    that has nowhere to go."""
    tools = []
    for name, spec in SUB_AGENT_REGISTRY.items():
        schema = TOOL_SCHEMAS[name]
        field_guidance = (schema.__doc__ or "").strip()
        description = f"{spec.description}\n\n{field_guidance}" if field_guidance else spec.description
        tools.append(StructuredTool.from_function(func=_undispatched, name=name, description=description, args_schema=compact_schema(schema.model_json_schema())))
    if include_memory:
        tools.append(
            StructuredTool.from_function(
                func=_undispatched,
                name=MEMORY_TOOL_NAME,
                description=(UpdateMemoryInput.__doc__ or "").strip(),
                args_schema=compact_schema(UpdateMemoryInput.model_json_schema()),
            )
        )
    if include_documents:
        tools.append(
            StructuredTool.from_function(
                func=_undispatched,
                name=DOCUMENT_TOOL_NAME,
                description=(SearchDocumentsInput.__doc__ or "").strip(),
                args_schema=compact_schema(SearchDocumentsInput.model_json_schema()),
            )
        )
    return tools
