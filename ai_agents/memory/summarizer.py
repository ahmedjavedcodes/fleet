"""Background sliding-window summarizer (agent-memory.md §2A and §5).

Never runs on the orchestrator's hot path: AgentMemory hands it a session id
when the backend reports more than 5 unsummarized messages, and it runs on a
background thread (or an attached asyncio.Queue worker).

The spec's `SELECT ... FOR UPDATE SKIP LOCKED` can't span an LLM call made
from another process over HTTP -- holding a row lock open across a multi-second
network round trip is exactly what the backend must never allow. The backend
instead makes the *commit* atomic: POST .../summary locks the session row,
checks summary_version, and SKIP-LOCKS the message rows being folded in. Two
overlapping summarizers may both do the LLM work, but exactly one commits;
the loser gets a 409 and discards its result. Same guarantee, no lock held
across I/O.
"""

from __future__ import annotations

import asyncio
import logging
import os
from concurrent.futures import Executor
from typing import Any

from langchain_core.messages import HumanMessage, SystemMessage

from core.llm_config import LLMProvider, get_chat_model
from mcp_server.memory_tools import apply_summary_tool, get_session_context_tool
from tools.api_client import BackendAPIError
from tools.auth_context import AgentContext

logger = logging.getLogger("fleet.memory")

# Most recent messages kept verbatim; everything older is folded into the summary.
WINDOW_SIZE = 4
MAX_SUMMARY_TOKENS = 1_000
MAX_RECOMPRESSIONS = 2

_SUMMARIZE_PROMPT = (
    "You maintain the running summary of a fleet-management assistant conversation. "
    "Merge the previous summary with the new messages into one concise summary. Keep "
    "every concrete fact the user may refer back to: vehicle plates, driver names, IDs, "
    "amounts, dates, decisions, stated preferences. Drop greetings and filler. Output "
    "only the summary text."
)


def estimate_tokens(text: str) -> int:
    """~4 characters per token -- good enough for a size budget, and avoids
    pulling in a tokenizer for a model the summary isn't even sent to."""
    return (len(text) + 3) // 4


def _default_llm():
    model = os.environ.get("MEMORY_SUMMARIZER_MODEL", os.environ.get("ORCHESTRATOR_MODEL", "openai/gpt-oss-20b"))
    return get_chat_model(LLMProvider.GROQ, model=model)


class SessionSummarizer:
    def __init__(
        self,
        *,
        llm: Any = None,
        window_size: int = WINDOW_SIZE,
        max_summary_tokens: int = MAX_SUMMARY_TOKENS,
        get_context=get_session_context_tool,
        apply_summary=apply_summary_tool,
    ) -> None:
        self._llm = llm
        self.window_size = window_size
        self.max_summary_tokens = max_summary_tokens
        self._get_context = get_context
        self._apply_summary = apply_summary
        self._queue: asyncio.Queue | None = None

    @property
    def llm(self):
        # Built lazily: constructing OrchestratorDeps must not require GROQ_API_KEY.
        if self._llm is None:
            self._llm = _default_llm()
        return self._llm

    def _invoke(self, instruction: str, body: str) -> str:
        response = self.llm.invoke([SystemMessage(content=instruction), HumanMessage(content=body)])
        return str(getattr(response, "content", response)).strip()

    def summarize(self, context: AgentContext, session_id: str) -> bool:
        """Returns True if a new summary was committed. Never raises."""
        try:
            snapshot = self._get_context(context, session_id)
            session = snapshot["session"]
            messages = snapshot["unsummarized_messages"]
            to_fold = messages[: max(len(messages) - self.window_size, 0)]
            if not to_fold:
                return False

            transcript = "\n".join(f"{m['role']}: {m['content']}" for m in to_fold)
            summary = self._invoke(
                _SUMMARIZE_PROMPT,
                f"Previous summary:\n{session['running_summary'] or '(none)'}\n\nNew messages:\n{transcript}",
            )
            # Recursive re-summarization: the summary itself must stay bounded.
            for _ in range(MAX_RECOMPRESSIONS):
                if estimate_tokens(summary) <= self.max_summary_tokens:
                    break
                summary = self._invoke(
                    f"Compress this summary to under {self.max_summary_tokens} tokens without dropping "
                    "plates, names, IDs, amounts, or stated preferences. Output only the summary.",
                    summary,
                )
            if estimate_tokens(summary) > self.max_summary_tokens:
                summary = summary[: self.max_summary_tokens * 4]

            self._apply_summary(
                context,
                session_id,
                message_ids=[m["id"] for m in to_fold],
                running_summary=summary,
                expected_summary_version=session["summary_version"],
            )
            return True
        except BackendAPIError as exc:
            if exc.status_code == 409:
                logger.info("summarizer: session %s already summarized concurrently, discarding", session_id)
            else:
                logger.warning("summarizer: backend rejected summary for session %s: %s", session_id, exc)
            return False
        except Exception:  # noqa: BLE001 -- background work must never surface into a user turn
            logger.exception("summarizer: failed for session %s", session_id)
            return False

    # ---- dispatch ----

    def attach_queue(self, queue: asyncio.Queue) -> None:
        self._queue = queue

    def enqueue(self, context: AgentContext, session_id: str, *, executor: Executor) -> None:
        if self._queue is not None:
            self._queue.put_nowait((context, session_id))
        else:
            executor.submit(self.summarize, context, session_id)

    async def run_worker(self, queue: asyncio.Queue) -> None:
        while True:
            context, session_id = await queue.get()
            try:
                await asyncio.to_thread(self.summarize, context, session_id)
            finally:
                queue.task_done()
