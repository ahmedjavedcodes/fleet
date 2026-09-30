"""RAG triad telemetry (hybrid-document-rag-pipeline.md §4.2).

An LLM-as-a-judge scores a sample (default 5%) of turns that used
search_documents on context relevance, faithfulness and answer relevance.
It runs on a background thread after the turn has already been answered, so
it never adds latency, and it fails open: a judge outage or unparseable
verdict is logged and dropped, never raised into a user turn.

Like FleetLiveObserver's telemetry, results go to an injectable sink that
defaults to local logging -- no metrics backend exists in this project.
Scores below target are logged at WARNING so degradation is visible.
"""

from __future__ import annotations

import json
import logging
import os
import random
import re
from concurrent.futures import Executor, Future, ThreadPoolExecutor
from datetime import datetime, timezone
from typing import Any, Callable

from langchain_core.messages import HumanMessage, SystemMessage
from pydantic import BaseModel, Field

logger = logging.getLogger("fleet.rag_eval")

SAMPLE_RATE = 0.05

# metric -> (comparison, target), per the spec's table
TARGETS: dict[str, tuple[str, float]] = {
    "context_relevance": (">", 0.85),
    "faithfulness": (">=", 1.0),
    "answer_relevance": (">", 0.90),
}

_JUDGE_PROMPT = (
    "You grade a retrieval-augmented answer. Score each metric from 0.0 to 1.0.\n"
    "- context_relevance: are the retrieved passages applicable to the question, or noise?\n"
    "- faithfulness: does the answer rely ONLY on the passages, with no numbers, names or facts "
    "absent from them? 1.0 means fully grounded. If the passages were empty and the answer says "
    "the documents don't cover it, that is faithful.\n"
    "- answer_relevance: does the answer directly address the question's core intent?\n"
    'Reply with JSON only: {"context_relevance": x, "faithfulness": y, "answer_relevance": z}'
)


class RagTriadScores(BaseModel):
    context_relevance: float = Field(ge=0.0, le=1.0)
    faithfulness: float = Field(ge=0.0, le=1.0)
    answer_relevance: float = Field(ge=0.0, le=1.0)


class RagTriadResult(BaseModel):
    organization_id: str
    question: str
    scores: RagTriadScores
    below_target: list[str]
    evaluated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


def _meets(value: float, comparison: str, target: float) -> bool:
    return value > target if comparison == ">" else value >= target


def log_sink(result: RagTriadResult) -> None:
    if result.below_target:
        logger.warning("RAG triad below target %s: %s", result.below_target, result.model_dump(mode="json"))
    else:
        logger.info("RAG triad: %s", result.scores.model_dump())


def _default_judge():
    from core.llm_failover import get_resilient_chat_model

    model = os.environ.get("RAG_JUDGE_MODEL", os.environ.get("ORCHESTRATOR_MODEL", "openai/gpt-oss-20b"))
    return get_resilient_chat_model(groq_model=model)


def _parse_scores(text: str) -> RagTriadScores:
    match = re.search(r"\{.*\}", text, re.DOTALL)
    if match is None:
        raise ValueError("judge returned no JSON object")
    raw = json.loads(match.group(0))
    return RagTriadScores(**{k: min(1.0, max(0.0, float(raw[k]))) for k in TARGETS})


class RagTriadEvaluator:
    def __init__(
        self,
        *,
        judge_llm: Any = None,
        sample_rate: float = SAMPLE_RATE,
        rng: Callable[[], float] = random.random,
        executor: Executor | None = None,
        sink: Callable[[RagTriadResult], None] = log_sink,
    ) -> None:
        self._judge = judge_llm
        self.sample_rate = sample_rate
        self.rng = rng
        self.executor = executor or ThreadPoolExecutor(max_workers=1, thread_name_prefix="rag-eval")
        self.sink = sink

    @property
    def judge(self):
        if self._judge is None:  # lazy: constructing the evaluator must not need GROQ_API_KEY
            self._judge = _default_judge()
        return self._judge

    def maybe_evaluate(self, organization_id: str, question: str, contexts: list[str], answer: str) -> Future | None:
        if self.rng() >= self.sample_rate:
            return None
        return self.executor.submit(self.evaluate, organization_id, question, contexts, answer)

    def evaluate(self, organization_id: str, question: str, contexts: list[str], answer: str) -> RagTriadResult | None:
        try:
            response = self.judge.invoke([
                SystemMessage(content=_JUDGE_PROMPT),
                HumanMessage(content=f"Question:\n{question}\n\nRetrieved passages:\n" + ("\n---\n".join(contexts) or "(none)")
                             + f"\n\nAnswer:\n{answer}"),
            ])
            scores = _parse_scores(str(getattr(response, "content", response)))
            result = RagTriadResult(
                organization_id=organization_id,
                question=question,
                scores=scores,
                below_target=[m for m, (cmp, target) in TARGETS.items() if not _meets(getattr(scores, m), cmp, target)],
            )
            self.sink(result)
            return result
        except Exception:  # noqa: BLE001 -- telemetry must never affect the conversation
            logger.warning("RAG triad evaluation failed; sample dropped", exc_info=True)
            return None
