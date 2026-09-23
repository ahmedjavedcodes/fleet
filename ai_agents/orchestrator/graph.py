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
import time
from dataclasses import dataclass, field
from typing import Any, Callable

from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, SystemMessage, ToolMessage
from langgraph.graph import END, StateGraph

from core.llm_config import LLMProvider, get_chat_model
from orchestrator.cache import ExecutionCache
from orchestrator.callbacks import FleetLiveObserver
from orchestrator.normalization import normalize_tool_args
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
    # Optional per fleet-live-observer.md -- None means no telemetry/UI
    # streaming at all, which is how every pre-existing test still runs
    # unchanged. OrchestratorSession is responsible for constructing one
    # and calling observer.start_turn() per user turn (FR 4).
    observer: FleetLiveObserver | None = None
    # Optional per execution-pre_hooks.md -- None means no caching at all,
    # which is how every pre-existing test still runs unchanged.
    cache: ExecutionCache | None = None


def _llm_usage(response: Any) -> tuple[int, int]:
    """Best-effort token extraction -- providers disagree on where this
    lives (AIMessage.usage_metadata vs. response_metadata['token_usage']),
    and neither is guaranteed present (e.g. a scripted test LLM)."""
    usage = getattr(response, "usage_metadata", None)
    if usage:
        return usage.get("input_tokens", 0), usage.get("output_tokens", 0)
    usage = (getattr(response, "response_metadata", None) or {}).get("token_usage") or {}
    return usage.get("prompt_tokens", 0), usage.get("completion_tokens", 0)


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

        if deps.observer is not None:
            deps.observer.record_node("plan")

        bound = deps.llm.bind_tools(build_llm_tools())
        start = time.monotonic()
        response = bound.invoke(_history_to_messages(state))
        latency_ms = int((time.monotonic() - start) * 1000)

        if deps.observer is not None:
            prompt_tokens, completion_tokens = _llm_usage(response)
            deps.observer.record_llm(
                model_name=getattr(deps.llm, "model_name", "unknown"),
                prompt_tokens=prompt_tokens, completion_tokens=completion_tokens, latency_ms=latency_ms,
            )

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
            call_id = call.get("id") or f"hop-{hop}-{agent_name}"
            call_args = call.get("args", {})

            if deps.observer is not None:
                deps.observer.start_tool_call(call_id, agent_name, call_args)

            if agent_name not in SUB_AGENT_REGISTRY:
                observation = f"Unknown tool {agent_name!r}."
                scratchpad.append({"hop": hop, "tool": agent_name, "args": call_args, "observation": observation})
                if deps.observer is not None:
                    deps.observer.record_tool_result(
                        call_id, agent_name, call_args, attempt=1, status="halted", observation_text=observation
                    )
                continue

            # Normalization pre-hook (execution-pre_hooks.md §3): deterministic
            # cleanup keyed by field name, applied before validation. Zero-failure
            # tolerance is normalize_tool_args' own job -- this call cannot raise.
            normalized_args = normalize_tool_args(agent_name, call_args)

            # attempt is 1-indexed and counts consecutive validation failures
            # for THIS tool across hops -- a fresh call after any success (or
            # a different tool) starts back at 1. This is what actually
            # enforces MAX_RETRIES (FR 7); a hardcoded attempt=1 here would
            # never reach retries_exhausted.
            attempt = retry_counts.get(agent_name, 0) + 1
            try:
                validated = validate_tool_args(TOOL_SCHEMAS[agent_name], normalized_args, attempt=attempt)
            except ToolValidationError as exc:
                # FR 8: every schema_error attempt gets its own trace (same
                # trace_id, incrementing attempt) whether or not this is the
                # one that ultimately exhausts retries -- billing sums all
                # attempts even though the turn as a whole may hard-fault.
                if deps.observer is not None:
                    deps.observer.record_tool_result(
                        call_id, agent_name, normalized_args, attempt=attempt, status="schema_error",
                        observation_text=exc.observation,
                    )
                if exc.retries_exhausted:
                    return {
                        **state,
                        "scratchpad": scratchpad,
                        "hop_count": hop,
                        "stage": "halted",
                        "halt_reason": exc.observation,
                    }
                retry_counts[agent_name] = attempt
                scratchpad.append({"hop": hop, "tool": agent_name, "args": normalized_args, "observation": exc.observation})
                continue

            retry_counts[agent_name] = 0
            validated_dict = validated.model_dump(exclude_none=True)

            # Cache pre-hook (execution-pre_hooks.md §4): only ever checked
            # for a read-only call on an agent the cache config enables --
            # a mutating call always reaches runner.run, never a cache.
            cache_eligible = deps.cache is not None and _is_read_only_call(agent_name, validated_dict)
            if cache_eligible:
                cached = deps.cache.check(
                    agent_name, validated_dict, auth_context.get("organization_id") or "", raw_args=normalized_args
                )
                if cached is not None:
                    scratchpad.append({"hop": hop, "tool": agent_name, "args": normalized_args, "observation": cached})
                    if deps.observer is not None:
                        deps.observer.record_tool_result(
                            call_id, agent_name, normalized_args, attempt=attempt, status="done", observation_text=cached
                        )
                    continue  # sub-agent runner is entirely bypassed on a cache hit

            sub_state: dict[str, Any] = {
                "token": auth_context.get("token"),
                **validated_dict,
            }
            if sub_state.get("document_type") and state.get("_pending_image_bytes") is not None:
                sub_state["image_bytes"] = state["_pending_image_bytes"]
                sub_state["mime_type"] = state.get("_pending_mime_type") or "image/jpeg"

            result = deps.runner.run(agent_name, sub_state)

            if result.status == "awaiting_approval":
                if deps.observer is not None:
                    deps.observer.record_tool_result(
                        call_id, agent_name, normalized_args, attempt=attempt, status="awaiting_approval",
                        observation_text="Paused for approval.", raw_result=result.state,
                    )
                    deps.observer.record_hitl_pause()
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
            scratchpad.append({"hop": hop, "tool": agent_name, "args": normalized_args, "observation": observation})
            if deps.observer is not None:
                deps.observer.record_tool_result(
                    call_id, agent_name, normalized_args, attempt=attempt, status=result.status,
                    observation_text=observation, raw_result=result.state,
                )
            # Only successful reads are cached -- a "halted" result (e.g. a
            # transient backend timeout) staying cached for ttl_seconds would
            # keep returning stale failures after the underlying issue clears.
            if cache_eligible and result.status == "done":
                deps.cache.store(agent_name, validated_dict, auth_context.get("organization_id") or "", observation, raw_args=normalized_args)

        return {**state, "scratchpad": scratchpad, "hop_count": hop, "stage": "planning", "_tool_retry_counts": retry_counts}

    return execute_tool


# Populated only on a WRITE-triggering call for that agent (see each
# agent's own classify_intent for the authoritative structural routing);
# insights is omitted entirely since it has no mutating nodes at all and
# is therefore always read-only regardless of which fields are set.
_WRITE_INDICATOR_FIELDS = frozenset({
    "assign_request", "terminate_request",  # assignment
    "document_type", "document_text",  # foundation / fuel / maintenance / accountability onboarding
    "trip_fields",  # fuel
    "provided_fields",  # foundation follow-up write
})


def _is_read_only_call(agent_name: str, validated_args: dict[str, Any]) -> bool:
    spec = SUB_AGENT_REGISTRY.get(agent_name)
    if spec is not None and not spec.mutating_nodes:
        return True  # e.g. insights -- never writes, regardless of args
    return not any(validated_args.get(field) for field in _WRITE_INDICATOR_FIELDS)


def _format_observation(agent_name: str, result: RunResult) -> str:
    if result.status == "halted":
        return f"{agent_name} halted: {result.state.get('halt_reason')}"
    for key in ("created_record", "query_result", "audit_result", "updated_parts", "fleet_health", "cost_correlation"):
        if result.state.get(key) is not None:
            return f"{agent_name} succeeded: {key}={result.state[key]!r}"
    return f"{agent_name} completed with no reportable result."


def _make_synthesize_node(deps: OrchestratorDeps):
    def synthesize(state: OrchestratorState) -> OrchestratorState:
        if deps.observer is not None:
            deps.observer.record_node("synthesize")

        messages = _history_to_messages(state) + [HumanMessage(content=_SYNTHESIS_PROMPT)]
        start = time.monotonic()
        response = deps.llm.invoke(messages)
        latency_ms = int((time.monotonic() - start) * 1000)

        if deps.observer is not None:
            prompt_tokens, completion_tokens = _llm_usage(response)
            deps.observer.record_llm(
                model_name=getattr(deps.llm, "model_name", "unknown"),
                prompt_tokens=prompt_tokens, completion_tokens=completion_tokens, latency_ms=latency_ms,
            )

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
