""""Truth Checker" post-hook: output fact-checking guardrail, per
execution-post_hooks.md §4.

Runs as a graph node between synthesize and END. A hallucination verdict
routes back to synthesize with a correction instruction instead of
returning straight to the user.

One correction to the spec: it names `llama3-8b-8192` as the "fast,
secondary LLM", but that model is not available on this Groq account (see
grand-orchestrator.md's own Constraints correction, which hit the same
issue for the main routing LLM). FACT_CHECKER_MODEL defaults to
ORCHESTRATOR_MODEL's own default (openai/gpt-oss-20b, confirmed working on
this account) rather than a model that would 404 on every call.

Fail-open by design: check_response_against_scratchpad returns False (i.e.
"no hallucination detected") on ANY exception -- a checker outage (bad API
key, network error, unparseable reply) must never block a legitimate
response from reaching the user. This mirrors every other optional hook in
this codebase (FleetLiveObserver, AlertDispatcher): auxiliary safety
machinery degrades to a no-op, it never becomes a new point of failure for
the primary path.
"""

from __future__ import annotations

import logging
import os
from typing import Any

from langchain_core.messages import HumanMessage, SystemMessage

from core.llm_config import LLMProvider, get_chat_model

logger = logging.getLogger("fleet.fact_check")

MAX_FACT_CHECK_RETRIES = 2

_CHECK_SYSTEM_PROMPT = (
    "You are a strict fact-checking guardrail. You will be shown a Scratchpad "
    "(ground-truth tool observations) and a Final Response (a draft summary of "
    "them). Does the Final Response contain any proper nouns, IDs, or numbers "
    "that do NOT appear in the Scratchpad? Reply with exactly one word: YES or NO."
)


def _default_fact_checker_llm():
    model = os.environ.get("FACT_CHECKER_MODEL", os.environ.get("ORCHESTRATOR_MODEL", "openai/gpt-oss-20b"))
    return get_chat_model(LLMProvider.GROQ, model=model)


def _scratchpad_to_text(scratchpad: list[dict[str, Any]]) -> str:
    return "\n".join(f"[{entry['tool']}] {entry['observation']}" for entry in scratchpad)


def check_response_against_scratchpad(llm: Any, scratchpad_text: str, final_response: str) -> bool:
    """Returns True iff the checker LLM flags a hallucination (YES). See
    module docstring: fails open (False) on any error."""
    if not final_response:
        return False
    try:
        messages = [
            SystemMessage(content=_CHECK_SYSTEM_PROMPT),
            HumanMessage(content=f"Scratchpad:\n{scratchpad_text}\n\nFinal Response:\n{final_response}"),
        ]
        response = llm.invoke(messages)
        verdict = str(getattr(response, "content", response)).strip().upper()
        return verdict.startswith("YES")
    except Exception:  # noqa: BLE001 -- fail open, see module docstring
        logger.exception("fact_check: checker LLM call failed, defaulting to no-hallucination")
        return False
