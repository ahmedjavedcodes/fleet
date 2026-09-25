"""Compiles each sub-agent graph with a checkpointer and interrupt_before on
its real mutating nodes, runs it, and distinguishes "finished" from
"paused for HITL approval" using LangGraph's own StateSnapshot.next --
non-empty means the next node hasn't run yet (interrupt_before fired), not
string-matching on `stage` (see grand-orchestrator.md FR 4 / AC 2-3).

One SubAgentRunner instance is held per orchestrator session (session.py),
so a thread paused by one hop's tool call can be resumed by a later
approve()/reject()/modify() call against the same in-memory checkpointer.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Any

from langgraph.checkpoint.memory import MemorySaver

from orchestrator.registry import SUB_AGENT_REGISTRY

_RunStatus = str  # "done" | "halted" | "awaiting_approval"


@dataclass
class RunResult:
    status: _RunStatus
    state: dict[str, Any]
    thread_id: str
    pending_node: str | None = None


class SubAgentRunner:
    def __init__(self) -> None:
        self._compiled: dict[str, Any] = {}

    def _compiled_graph(self, agent_name: str):
        if agent_name not in self._compiled:
            spec = SUB_AGENT_REGISTRY[agent_name]
            checkpointer = MemorySaver()
            self._compiled[agent_name] = spec.build_graph(spec.deps_factory()).compile(
                checkpointer=checkpointer, interrupt_before=list(spec.mutating_nodes) or None
            )
        return self._compiled[agent_name]

    def run(self, agent_name: str, input_state: dict[str, Any], *, thread_id: str | None = None) -> RunResult:
        graph = self._compiled_graph(agent_name)
        thread_id = thread_id or str(uuid.uuid4())
        config = {"configurable": {"thread_id": thread_id}}
        graph.invoke(input_state, config=config)
        return self._observe(graph, config, thread_id)

    def resume(self, agent_name: str, thread_id: str, *, updates: dict[str, Any] | None = None) -> RunResult:
        """updates merges into the paused sub-agent's state before resuming
        -- how a HITL "modify" signal is applied (grand-orchestrator.md's
        modify edge case)."""
        graph = self._compiled_graph(agent_name)
        config = {"configurable": {"thread_id": thread_id}}
        if updates:
            graph.update_state(config, updates)
        graph.invoke(None, config=config)
        return self._observe(graph, config, thread_id)

    def _observe(self, graph: Any, config: dict[str, Any], thread_id: str) -> RunResult:
        snapshot = graph.get_state(config)
        if snapshot.next:
            return RunResult(
                status="awaiting_approval", state=dict(snapshot.values), thread_id=thread_id, pending_node=snapshot.next[0]
            )
        state = dict(snapshot.values)
        status = "halted" if state.get("stage") == "halted" else "done"
        return RunResult(status=status, state=state, thread_id=thread_id)
