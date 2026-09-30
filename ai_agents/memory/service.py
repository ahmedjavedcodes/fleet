"""AgentMemory: the single object the Grand Orchestrator holds for memory
(OrchestratorDeps.memory). Everything goes through the backend's
/api/v1/memory endpoints -- ai_agents never touches Postgres directly.

Hot path vs background:
  - fetch_context      hot path; the graph node bounds it with a hard timeout.
  - save_memory        on explicit HITL approval only; the user is waiting for it.
  - record_message     background (single FIFO worker, so user/assistant order holds).
  - on_write           background (staleness post-hook).
  - summarization      background, triggered by record_message.
"""

from __future__ import annotations

import logging
from concurrent.futures import Executor, Future, ThreadPoolExecutor
from typing import Any

from memory.embeddings import Embedder, get_default_embedder
from memory.staleness import extract_entity_facts
from memory.summarizer import SessionSummarizer
from mcp_server import memory_tools
from tools.api_client import BackendAPIError
from tools.auth_context import AgentContext

logger = logging.getLogger("fleet.memory")

# Measured ~0.45s per backend call on the dev stack; the two reads below run
# concurrently, so this leaves headroom while staying far below one LLM call.
FETCH_TIMEOUT_SECONDS = 1.5
RECENT_MESSAGE_LIMIT = 6
# Cosine-distance cutoff for recall. Calibrated live against Pinecone's
# llama-text-embed-v2: a correct paraphrase match ("what currency should I
# show expenses in?" -> "User prefers ... PKR") scored 0.675, above the
# backend's generic 0.5 default; an unrelated fact scored > 0.8.
MAX_RECALL_DISTANCE = 0.75

# Separate from the single-worker `background` executor: that one serializes
# message writes, and a hot-path read must never queue behind them.
_FETCH_POOL = ThreadPoolExecutor(max_workers=4, thread_name_prefix="memory-summary-read")


class AgentMemory:
    def __init__(
        self,
        *,
        embedder: Embedder | None = None,
        summarizer: SessionSummarizer | None = None,
        tools: Any = memory_tools,
        background: Executor | None = None,
        fetch_timeout_s: float = FETCH_TIMEOUT_SECONDS,
        top_k: int = 5,
        max_distance: float = MAX_RECALL_DISTANCE,
    ) -> None:
        self.embedder = embedder or get_default_embedder()
        self.summarizer = summarizer or SessionSummarizer()
        self.tools = tools
        # One worker: message appends must land in the order they were said.
        self.background = background or ThreadPoolExecutor(max_workers=1, thread_name_prefix="agent-memory")
        self.fetch_timeout_s = fetch_timeout_s
        self.top_k = top_k
        self.max_distance = max_distance

    def _embed(self, text: str, *, task: str) -> list[float] | None:
        """Embedding failure degrades to scope/keyword recall -- never an error."""
        try:
            return self.embedder.embed(text, task=task)
        except Exception:  # noqa: BLE001
            logger.warning("memory: embedding failed, continuing without a vector", exc_info=True)
            return None

    # ---- sessions (short-term) ----

    def start_session(self, context: AgentContext) -> str:
        return str(self.tools.create_session_tool(context)["id"])

    def load_history(self, context: AgentContext, session_id: str) -> list[dict[str, str]]:
        snapshot = self.tools.get_session_context_tool(context, session_id)
        return [{"role": m["role"], "content": m["content"]} for m in snapshot["unsummarized_messages"]]

    def record_message(self, context: AgentContext, session_id: str, role: str, content: str) -> Future:
        return self.background.submit(self._record_message, context, session_id, role, content)

    def _record_message(self, context: AgentContext, session_id: str, role: str, content: str) -> None:
        try:
            result = self.tools.append_message_tool(context, session_id, role, content)
            if result.get("needs_summarization"):
                self.summarizer.enqueue(context, session_id, executor=self.background)
        except Exception:  # noqa: BLE001 -- a lost transcript line must never break the conversation
            logger.exception("memory: failed to record %s message for session %s", role, session_id)

    # ---- read path (hot) ----

    def fetch_context(self, context: AgentContext, session_id: str | None, query_text: str) -> str | None:
        """Assembles the memory block for the Mega-Prompt. May raise -- the
        caller (graph.py's fetch_memory node) owns timeout and fail-open."""
        sections: list[str] = []

        # The session summary and the fact search are independent reads, so
        # they run side by side -- sequential, they'd cost two round trips.
        summary_future = (
            _FETCH_POOL.submit(self.tools.get_session_context_tool, context, session_id, timeout=self.fetch_timeout_s)
            if session_id
            else None
        )

        embedding = self._embed(query_text, task="search_query") if query_text else None
        payload: dict[str, Any] = {"top_k": self.top_k}
        if embedding is not None:
            payload["embedding"] = embedding
            payload["max_distance"] = self.max_distance
        elif query_text:
            payload["query_text"] = query_text
        facts = self.tools.search_memories_tool(context, payload, timeout=self.fetch_timeout_s)

        if summary_future is not None:
            session = summary_future.result()["session"]
            if session.get("running_summary"):
                sections.append(f"Earlier in this conversation:\n{session['running_summary']}")

        if facts:
            lines = []
            for fact in facts:
                where = f"{fact['entity_type']} {fact['entity_id']}" if fact.get("entity_id") else fact["scope"]
                lines.append(f"- [{where}] {fact['content']}")
            sections.append("Remembered facts:\n" + "\n".join(lines))

        return "\n\n".join(sections) or None

    # ---- write path ----

    def save_memory(self, context: AgentContext, request: dict[str, Any]) -> dict[str, Any]:
        """Only ever called after explicit human approval (update_memory HITL).
        Raises BackendAPIError so the caller can report e.g. a 403 honestly."""
        payload = {k: v for k, v in request.items() if v is not None}
        embedding = self._embed(request["content"], task="search_document")
        if embedding is not None:
            payload["embedding"] = embedding
        return self.tools.create_memory_tool(context, payload)

    def on_write(self, agent_name: str, raw_result: dict[str, Any], context: AgentContext) -> Future | None:
        """Staleness post-hook. Never raises; returns the background future
        (tests wait on it) or None when the write produced no entity facts."""
        try:
            facts = extract_entity_facts(agent_name, raw_result or {})
        except Exception:  # noqa: BLE001
            logger.exception("memory: staleness extraction failed for %s", agent_name)
            return None
        if not facts:
            return None
        return self.background.submit(self._supersede_all, context, facts)

    def _supersede_all(self, context: AgentContext, facts) -> None:
        for fact in facts:
            payload: dict[str, Any] = {"entity_id": fact.entity_id, "entity_type": fact.entity_type, "content": fact.content}
            embedding = self._embed(fact.content, task="search_document")
            if embedding is not None:
                payload["embedding"] = embedding
            try:
                self.tools.supersede_memories_tool(context, payload)
            except BackendAPIError as exc:
                # e.g. 403 for a driver filing an incident: entity facts are
                # manager/mechanic-writable only. Logged, not surfaced.
                logger.info("memory: staleness write for %s %s skipped: %s", fact.entity_type, fact.entity_id, exc)
            except Exception:  # noqa: BLE001
                logger.exception("memory: staleness write failed for %s %s", fact.entity_type, fact.entity_id)
