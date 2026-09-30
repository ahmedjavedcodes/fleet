"""FleetLiveObserver: async LangChain callback handler + sync-safe telemetry
recorder for the Grand Orchestrator, per fleet-live-observer.md.

Two audiences, two channels:
  - UI channel: interpolated strings pushed to `ui_messages` (always) and,
    when a caller attaches one, an `asyncio.Queue` an SSE endpoint could
    drain concurrently.
  - Telemetry channel: redacted LLMTrace/ToolTrace pushed the same way,
    drained by `run_worker` in batches to an injectable async `sink`.

Architectural notes the spec doesn't anticipate, resolved here:

1. orchestrator/graph.py's execute_tool node dispatches sub-agents itself
   (reading tool_calls directly off the LLM's response, see graph.py's
   module docstring) rather than through LangChain's own tool-execution
   runtime -- so on_tool_start/on_tool_end never fire automatically just by
   attaching this handler to a graph run. graph.py calls this observer's
   plain sync methods (record_node, start_tool_call, record_tool_result)
   explicitly at the right points instead. The real AsyncCallbackHandler
   methods below are provided for a future async execution path
   (graph.astream_events with this handler in a RunnableConfig) where they
   WOULD fire correctly, since plan/synthesize's LLM calls are genuine
   LangChain Runnable invocations -- they just aren't reached by today's
   synchronous graph.

2. Redaction must run on raw structured data, not on an already-formatted
   string. graph.py's own _format_observation() builds an LLM-facing
   scratchpad string via repr() for the model's reasoning context (which
   intentionally sees real data -- redaction is for the audit trail, not
   the model's working memory). record_tool_result() takes that raw
   sub-agent result state as `raw_result` and redacts THAT for the stored
   trace, independent of what the scratchpad shows the LLM.

3. No backend endpoint exists to persist traces to Postgres, and ai_agents/
   is not permitted to write to the database directly (root CLAUDE.md,
   ai_agents/CLAUDE.md's cross-module boundary rule). The default sink logs
   locally via `logging`, which is FR 6's own fallback anyway. Swapping in
   a real sink (POSTing to a future backend telemetry endpoint) is a
   one-line change once that endpoint exists.
"""

from __future__ import annotations

import asyncio
import logging
import time
import uuid
from typing import Any, Awaitable, Callable
from uuid import UUID

from langchain_core.callbacks import AsyncCallbackHandler
from langchain_core.outputs import LLMResult

from orchestrator.audit_schemas import LLMTrace, ToolStatus, ToolTrace
from orchestrator.redact import redact_payload
from orchestrator.ui_interpolation import HITL_PAUSE_MESSAGE, interpolate_node, interpolate_tool_start

logger = logging.getLogger("fleet.telemetry")

TraceSink = Callable[[LLMTrace | ToolTrace], Awaitable[None]]

# Activity attributed to the orchestrator itself (planning, drafting, HITL pause)
# rather than to one of the tools.
ORCHESTRATOR_AGENT = "orchestrator"


async def log_sink(trace: LLMTrace | ToolTrace) -> None:
    """Default sink -- see module docstring point 3."""
    logger.info("telemetry: %s", trace.model_dump(mode="json"))


class FleetLiveObserver(AsyncCallbackHandler):
    def __init__(
        self,
        *,
        organization_id: str,
        user_id: str,
        role: str,
        sink: TraceSink = log_sink,
        ui_sink: Callable[[str], None] | None = None,
        activity_sink: Callable[[str, str], None] | None = None,
        model_name: str = "unknown",
    ) -> None:
        self.organization_id = organization_id
        self.user_id = user_id
        self.role = role
        self.sink = sink
        self.ui_sink = ui_sink
        # (agent, message) -- the same UI strings, attributed to the agent doing
        # the work, for a live activity feed. Reassignable per turn by the caller.
        self.activity_sink = activity_sink
        self.model_name = model_name

        self.trace_id: str = str(uuid.uuid4())
        self.ui_messages: list[str] = []
        self.traces: list[LLMTrace | ToolTrace] = []

        self._queue: asyncio.Queue | None = None
        self._llm_start_times: dict[UUID, float] = {}
        self._tool_start_times: dict[str, float] = {}

    # ---- turn lifecycle ----

    def start_turn(self) -> str:
        """Fresh trace_id per session turn (FR 4) -- OrchestratorSession
        calls this once at the start of run(). approve()/modify()/reject()
        deliberately do not: an approval round-trip is part of the turn that
        paused, so its traces share that turn's trace_id."""
        self.trace_id = str(uuid.uuid4())
        self.ui_messages = []
        return self.trace_id

    def attach_queue(self, queue: asyncio.Queue) -> None:
        """Opt-in: only needed by an async caller (e.g. a future SSE
        endpoint) that wants to drain traces concurrently via run_worker.
        The sync graph path never calls this and works fine without it."""
        self._queue = queue

    async def run_worker(self, queue: asyncio.Queue, *, batch_size: int = 20) -> None:
        """Background consumer (FR 7): drains `queue` in batches and calls
        `self.sink` for each. Runs until cancelled -- the caller owns the
        task's lifecycle (create_task/cancel)."""
        while True:
            batch = [await queue.get()]
            while len(batch) < batch_size and not queue.empty():
                batch.append(queue.get_nowait())
            for trace in batch:
                await self._safe_sink(trace)
            for _ in batch:
                queue.task_done()

    async def _safe_sink(self, trace: LLMTrace | ToolTrace) -> None:
        try:
            await self.sink(trace)
        except Exception:  # noqa: BLE001 -- FR 6: telemetry must never break the caller
            logger.exception("FleetLiveObserver: sink failed for trace_id=%s", trace.trace_id)

    def _emit_ui(self, message: str, agent: str = ORCHESTRATOR_AGENT) -> None:
        try:
            self.ui_messages.append(message)
            if self.ui_sink is not None:
                self.ui_sink(message)
            if self.activity_sink is not None:
                self.activity_sink(agent, message)
        except Exception:  # noqa: BLE001 -- FR 6
            logger.exception("FleetLiveObserver: UI sink failed")

    def _emit_trace(self, trace: LLMTrace | ToolTrace) -> None:
        try:
            self.traces.append(trace)
            if self._queue is not None:
                self._queue.put_nowait(trace)
            else:
                # No async queue attached (the sync graph path) -- log
                # inline via the same fallback FR 6 asks for, rather than
                # silently dropping the trace.
                logger.info("telemetry (sync path): %s", trace.model_dump(mode="json"))
        except Exception:  # noqa: BLE001 -- FR 6
            logger.exception("FleetLiveObserver: failed to emit trace")

    # ---- sync-safe recording API, called directly by orchestrator/graph.py ----

    def record_node(self, node_name: str) -> str:
        try:
            message = interpolate_node(node_name)
        except Exception:  # noqa: BLE001 -- FR 6
            logger.exception("FleetLiveObserver: node interpolation failed for %r", node_name)
            message = "Working on it..."
        self._emit_ui(message)
        return message

    def record_hitl_pause(self) -> str:
        self._emit_ui(HITL_PAUSE_MESSAGE)
        return HITL_PAUSE_MESSAGE

    def start_tool_call(self, call_id: str, tool_name: str, args: dict[str, Any]) -> str:
        self._tool_start_times[call_id] = time.monotonic()
        try:
            message = interpolate_tool_start(tool_name, args)
        except Exception:  # noqa: BLE001 -- FR 6
            logger.exception("FleetLiveObserver: tool interpolation failed for %r", tool_name)
            message = "Working on it..."
        self._emit_ui(message, tool_name)
        return message

    def record_tool_result(
        self,
        call_id: str,
        agent_name: str,
        args: dict[str, Any],
        *,
        attempt: int,
        status: ToolStatus,
        observation_text: str,
        raw_result: dict[str, Any] | None = None,
    ) -> None:
        """observation_text is what the scratchpad already shows the LLM
        (unredacted, by design -- see module docstring point 2). raw_result,
        when given, is redacted independently for the STORED trace; when
        omitted, the trace falls back to the already-plain observation_text
        (a formatted string has no dict keys left to redact by)."""
        try:
            started_at = self._tool_start_times.pop(call_id, None)
            latency_ms = int((time.monotonic() - started_at) * 1000) if started_at is not None else 0

            stored_observation = str(redact_payload(raw_result)) if raw_result is not None else observation_text

            trace = ToolTrace(
                trace_id=self.trace_id,
                organization_id=self.organization_id,
                user_id=self.user_id,
                agent_name=agent_name,
                attempt=attempt,
                input_payload=redact_payload(args or {}),
                status=status,
                observation=stored_observation,
                latency_ms=latency_ms,
            )
        except Exception:  # noqa: BLE001 -- FR 6
            logger.exception("FleetLiveObserver: failed to build ToolTrace for %r", agent_name)
            return
        self._emit_trace(trace)

    def record_llm(self, *, model_name: str, prompt_tokens: int, completion_tokens: int, latency_ms: int) -> None:
        try:
            trace = LLMTrace(
                trace_id=self.trace_id,
                organization_id=self.organization_id,
                user_id=self.user_id,
                model_name=model_name,
                prompt_tokens=prompt_tokens,
                completion_tokens=completion_tokens,
                latency_ms=latency_ms,
            )
        except Exception:  # noqa: BLE001 -- FR 6
            logger.exception("FleetLiveObserver: failed to build LLMTrace")
            return
        self._emit_trace(trace)

    # ---- real AsyncCallbackHandler interface (FR 3) ----
    # See module docstring point 1: not reached by today's synchronous
    # graph.py, provided for a future async execution path.

    async def on_chat_model_start(
        self, serialized, messages, *, run_id, parent_run_id=None, tags=None, metadata=None, **kwargs
    ) -> None:
        try:
            self._llm_start_times[run_id] = time.monotonic()
        except Exception:  # noqa: BLE001 -- FR 6
            logger.exception("FleetLiveObserver.on_chat_model_start failed")

    async def on_llm_end(self, response: LLMResult, *, run_id, parent_run_id=None, tags=None, **kwargs) -> None:
        try:
            started_at = self._llm_start_times.pop(run_id, None)
            latency_ms = int((time.monotonic() - started_at) * 1000) if started_at is not None else 0

            usage = (response.llm_output or {}).get("token_usage", {})
            model_name = (response.llm_output or {}).get("model_name", self.model_name)

            self.record_llm(
                model_name=model_name,
                prompt_tokens=usage.get("prompt_tokens", 0),
                completion_tokens=usage.get("completion_tokens", 0),
                latency_ms=latency_ms,
            )
        except Exception:  # noqa: BLE001 -- FR 6
            logger.exception("FleetLiveObserver.on_llm_end failed")

    async def on_llm_error(self, error: BaseException, *, run_id, parent_run_id=None, tags=None, **kwargs) -> None:
        logger.warning("FleetLiveObserver: LLM error observed: %s", error)

    async def on_tool_start(
        self, serialized, input_str, *, run_id, parent_run_id=None, tags=None, metadata=None, inputs=None, **kwargs
    ) -> None:
        try:
            tool_name = (serialized or {}).get("name", "unknown")
            self.start_tool_call(str(run_id), tool_name, inputs or {})
        except Exception:  # noqa: BLE001 -- FR 6
            logger.exception("FleetLiveObserver.on_tool_start failed")

    async def on_tool_end(self, output: Any, *, run_id, parent_run_id=None, tags=None, **kwargs) -> None:
        # Real LangChain tool execution doesn't carry the agent_name/attempt
        # context that execute_tool's direct calls do. Left as a no-op stub
        # for the future async path; the sync graph never reaches this.
        pass

    async def on_tool_error(self, error: BaseException, *, run_id, parent_run_id=None, tags=None, **kwargs) -> None:
        logger.warning("FleetLiveObserver: tool error observed: %s", error)
