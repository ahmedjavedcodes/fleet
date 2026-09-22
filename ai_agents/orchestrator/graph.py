"""Grand Orchestrator: the ReAct hub-and-spoke loop over the six sub-agents.

Per grand-orchestrator.md section 3:

    plan -> [tool_calls present] -> execute_tool -> plan (loop)
                                                   -> END (HITL pause)
         -> [no tool_calls]      -> synthesize -> END

`execute_tool` is where FR 2 (immutable RBAC injection), FR 3 (structural
intent forcing), FR 4 (HITL interrupt), FR 6 (halt-aware evaluation), and
FR 7 (Pydantic retry) all actually happen -- `plan` and `synthesize` are
thin LLM calls around it.

A hop-count ceiling (MAX_HOPS) is a safety addition beyond the literal
spec text: nothing in grand-orchestrator.md bounds the ReAct loop, and an
unbounded loop against a live LLM is a real cost/availability risk.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Any, Callable

from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, SystemMessage, ToolMessage
from langgraph.graph import END, StateGraph

from core.llm_config import LLMProvider, get_chat_model
from orchestrator.registry import SUB_AGENT_REGISTRY
from orchestrator.retry import MAX_RETRIES, ToolValidationError, validate_tool_args
from orchestrator.runner import RunResult, SubAgentRunner
from orchestrator.state import OrchestratorState
from orchestrator.tool_schemas import TOOL_SCHEMAS
from orchestrator.tools import build_llm_tools

MAX_HOPS = 8

_SYSTEM_PROMPT = (
    "You are the Fleet SaaS Grand Orchestrator. You have six tools, one per "
    "specialized sub-agent (foundation, fuel, maintenance, accountability, "
    "insights, assignment) -- call read tools first to resolve names/plates "
    "into IDs before calling a write tool that needs them. Never invent an "
    "ID; only use one that appeared in a prior tool observation. When a tool "
    "reports it halted, do not retry it with the same arguments -- explain "
    "the failure instead. When you have enough information to answer the "
    "user, respond with no further tool calls."
)

_SYNTHESIS_PROMPT = (
    "Write a concise, natural-language confirmation of what happened, based "
    "only on the tool observations above. If anything halted or was "
    "rejected, say so plainly -- do not claim success for a failed step."
)


def _default_llm():
    # Spec named Llama-3-70B/8B, which this Groq account doesn't have access
    # to (see grand-orchestrator.md's Constraints correction); gpt-oss-20b
    # is confirmed to support tool-calling on this account and is the
    # smaller/faster of the two verified options.
    model = os.environ.get("ORCHESTRATOR_MODEL", "openai/gpt-oss-20b")
    return get_chat_model(LLMProvider.GROQ, model=model)


@dataclass
class OrchestratorDeps:
    """Injectable seams. llm defaults to the real Groq-calling model --
    unlike the vision-only providers used elsewhere, tool-calling is
    confirmed working on this account (see prompts.md), so this is exercised
    live, not just mocked, but is still fully injectable for deterministic
    tests."""

    llm: Any = field(default_factory=_default_llm)
    runner: SubAgentRunner = field(default_factory=SubAgentRunner)


def _history_to_messages(state: OrchestratorState) -> list[BaseMessage]:
    messages: list[BaseMessage] = [SystemMessage(content=_SYSTEM_PROMPT)]
    for turn in state.get("chat_history") or []:
        if turn["role"] == "user":
            messages.append(HumanMessage(content=turn["content"]))
        else:
            messages.append(AIMessage(content=turn["content"]))
    for entry in state.get("scratchpad") or []:
        messages.append(AIMessage(content="", tool_calls=[{"name": entry["tool"], "args": entry["args"], "id": f"hop-{entry['hop']}"}]))
        messages.append(ToolMessage(content=entry["observation"], tool_call_id=f"hop-{entry['hop']}"))
    return messages


def _make_plan_node(deps: OrchestratorDeps):
    def plan(state: OrchestratorState) -> OrchestratorState:
        if state.get("hop_count", 0) >= MAX_HOPS:
            return {
                **state,
                "stage": "halted",
                "halt_reason": f"Stopped after {MAX_HOPS} hops without resolving the request.",
                "active_tool_calls": [],
            }

        bound = deps.llm.bind_tools(build_llm_tools())
        response = bound.invoke(_history_to_messages(state))
        tool_calls = getattr(response, "tool_calls", None) or []

        return {**state, "active_tool_calls": tool_calls, "stage": "planning"}

    return plan


def _make_execute_tool_node(deps: OrchestratorDeps):
    def execute_tool(state: OrchestratorState) -> OrchestratorState:
        scratchpad = list(state.get("scratchpad") or [])
        hop = state.get("hop_count", 0) + 1
        auth_context = state.get("auth_context") or {}

        retry_counts = dict(state.get("_tool_retry_counts") or {})

        for call in state.get("active_tool_calls") or []:
            agent_name = call["name"]
            if agent_name not in SUB_AGENT_REGISTRY:
                observation = f"Unknown tool {agent_name!r}."
                scratchpad.append({"hop": hop, "tool": agent_name, "args": call.get("args", {}), "observation": observation})
                continue

            # attempt is 1-indexed and counts consecutive validation failures
            # for THIS tool across hops -- a fresh call after any success (or
            # a different tool) starts back at 1. This is what actually
            # enforces MAX_RETRIES (FR 7); a hardcoded attempt=1 here would
            # never reach retries_exhausted.
            attempt = retry_counts.get(agent_name, 0) + 1
            try:
                validated = validate_tool_args(TOOL_SCHEMAS[agent_name], call.get("args", {}), attempt=attempt)
            except ToolValidationError as exc:
                if exc.retries_exhausted:
                    return {
                        **state,
                        "scratchpad": scratchpad,
                        "hop_count": hop,
                        "stage": "halted",
                        "halt_reason": exc.observation,
                    }
                retry_counts[agent_name] = attempt
                scratchpad.append({"hop": hop, "tool": agent_name, "args": call.get("args", {}), "observation": exc.observation})
                continue

            retry_counts[agent_name] = 0

            sub_state: dict[str, Any] = {
                "token": auth_context.get("token"),
                **validated.model_dump(exclude_none=True),
            }
            if sub_state.get("document_type") and state.get("_pending_image_bytes") is not None:
                sub_state["image_bytes"] = state["_pending_image_bytes"]
                sub_state["mime_type"] = state.get("_pending_mime_type") or "image/jpeg"

            result = deps.runner.run(agent_name, sub_state)

            if result.status == "awaiting_approval":
                return {
                    **state,
                    "scratchpad": scratchpad,
                    "hop_count": hop,
                    "stage": "awaiting_approval",
                    "_tool_retry_counts": retry_counts,
                    "hitl_state": {
                        "agent_name": agent_name,
                        "thread_id": result.thread_id,
                        "tool_name": agent_name,
                        "pending_node": result.pending_node or "",
                        "state": result.state,
                    },
                }

            observation = _format_observation(agent_name, result)
            scratchpad.append({"hop": hop, "tool": agent_name, "args": call.get("args", {}), "observation": observation})

        return {**state, "scratchpad": scratchpad, "hop_count": hop, "stage": "planning", "_tool_retry_counts": retry_counts}

    return execute_tool


def _format_observation(agent_name: str, result: RunResult) -> str:
    if result.status == "halted":
        return f"{agent_name} halted: {result.state.get('halt_reason')}"
    for key in ("created_record", "query_result", "audit_result", "updated_parts", "fleet_health", "cost_correlation"):
        if result.state.get(key) is not None:
            return f"{agent_name} succeeded: {key}={result.state[key]!r}"
    return f"{agent_name} completed with no reportable result."


def _make_synthesize_node(deps: OrchestratorDeps):
    def synthesize(state: OrchestratorState) -> OrchestratorState:
        messages = _history_to_messages(state) + [HumanMessage(content=_SYNTHESIS_PROMPT)]
        response = deps.llm.invoke(messages)
        final_stage = "halted" if state.get("stage") == "halted" else "done"
        return {**state, "final_response": response.content, "stage": final_stage}

    return synthesize


def _route_after_plan(state: OrchestratorState) -> str:
    if state.get("stage") == "halted":
        return "synthesize"
    return "execute_tool" if state.get("active_tool_calls") else "synthesize"


def _route_after_execute(state: OrchestratorState) -> str:
    if state.get("stage") == "awaiting_approval":
        return "end"
    if state.get("stage") == "halted":
        return "synthesize"
    return "plan"


def build_orchestrator_graph(deps: OrchestratorDeps | None = None) -> StateGraph:
    deps = deps or OrchestratorDeps()
    graph = StateGraph(OrchestratorState)

    graph.add_node("plan", _make_plan_node(deps))
    graph.add_node("execute_tool", _make_execute_tool_node(deps))
    graph.add_node("synthesize", _make_synthesize_node(deps))

    graph.set_entry_point("plan")
    graph.add_conditional_edges("plan", _route_after_plan, {"execute_tool": "execute_tool", "synthesize": "synthesize"})
    graph.add_conditional_edges("execute_tool", _route_after_execute, {"plan": "plan", "synthesize": "synthesize", "end": END})
    graph.add_edge("synthesize", END)

    return graph


def get_compiled_orchestrator_graph(deps: OrchestratorDeps | None = None):
    return build_orchestrator_graph(deps).compile()
