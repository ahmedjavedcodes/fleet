"""Cost-bounded table summarization (hybrid-document-rag-pipeline.md §2.2).

Raw Markdown tables embed poorly, so each table (with its captured heading
context) is turned into a 3-4 sentence summary by a fast LLM. Bounded two
ways: at most `max_tables` per document, and 3 attempts per table with
exponential backoff. Anything that isn't summarized is indexed as its raw
Markdown -- the spec's own fallback -- so summarization can only improve a
document, never block it.

The LLM is Groq's OpenAI-compatible endpoint over plain httpx, so the backend
doesn't take a LangChain dependency for one prompt.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from typing import Callable

import httpx

logger = logging.getLogger("fleet.rag")

RETRY_DELAYS_SECONDS = (0.0, 1.0, 2.0)

_PROMPT = (
    "Summarize this table from a fleet-operations document in 3-4 plain sentences. "
    "Keep every part name, number, unit, interval, price and date exactly as written. "
    "Do not add information that is not in the table.\n\nContext: {context}\n\nTable:\n{table}"
)


@dataclass
class SummaryOutcome:
    # unit index -> (text to embed, text to store/return)
    texts: dict[int, tuple[str, str]] = field(default_factory=dict)
    summarized: int = 0
    failures: list[dict] = field(default_factory=list)  # for the ingest dead-letter log


def groq_completion(api_key: str, model: str, prompt: str, *, timeout: float = 20.0) -> str:
    response = httpx.post(
        "https://api.groq.com/openai/v1/chat/completions",
        headers={"Authorization": f"Bearer {api_key}"},
        json={"model": model, "messages": [{"role": "user", "content": prompt}], "temperature": 0},
        timeout=timeout,
    )
    response.raise_for_status()
    content = response.json()["choices"][0]["message"]["content"]
    if not content or not content.strip():
        raise ValueError("empty summary")
    return content.strip()


def summarize_tables(
    tables: list[tuple[int, str, str]],
    complete: Callable[[str], str] | None,
    *,
    max_tables: int,
    sleep: Callable[[float], None] = time.sleep,
    delays: tuple[float, ...] = RETRY_DELAYS_SECONDS,
) -> SummaryOutcome:
    """tables: (unit_index, markdown, context). complete=None means no LLM is
    configured: every table falls back to Markdown, with no failure logged
    (nothing failed -- summarization is simply off)."""
    outcome = SummaryOutcome()
    for position, (index, markdown, context) in enumerate(tables):
        fallback = f"{context}\n\n{markdown}".strip() if context else markdown
        if complete is None or position >= max_tables:
            outcome.texts[index] = (fallback, fallback)
            continue
        last_error: Exception | None = None
        for delay in delays:
            if delay:
                sleep(delay)
            try:
                summary = complete(_PROMPT.format(context=context or "(none)", table=markdown))
                # Embed the summary (the spec's point: raw tables embed badly),
                # but store summary + the exact table, so figures stay citable.
                outcome.texts[index] = (summary, f"{summary}\n\n{markdown}")
                outcome.summarized += 1
                break
            except Exception as exc:  # noqa: BLE001 -- any failure -> retry, then Markdown fallback
                last_error = exc
        else:
            outcome.texts[index] = (fallback, fallback)
            outcome.failures.append(
                {"unit_index": index, "error": f"{type(last_error).__name__}: {last_error}"[:500], "attempts": len(delays)}
            )
            logger.warning("table %d summarization failed after %d attempts; indexed as Markdown", index, len(delays))
    return outcome
