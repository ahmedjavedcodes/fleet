"""Spend tracking and the hard budget circuit-breaker for paid (OpenRouter) LLM calls.

Every paid call's cost is computed from the provider-reported token usage and added to a
small JSON file, so the total survives restarts. Once spend reaches LLM_BUDGET_USD, paid
models are skipped (the chain falls through to free ones) instead of draining the account.
Free providers (Groq's free tier, ":free" OpenRouter models, local Ollama) cost $0 and are
never blocked by it.
"""

from __future__ import annotations

import json
import logging
import os
import threading
from pathlib import Path

logger = logging.getLogger("fleet.llm")

# USD per million tokens (input, output), from OpenRouter's public price list. Unknown paid
# models are billed at the conservative fallback so the breaker errs toward tripping early.
PRICES_PER_MILLION: dict[str, tuple[float, float]] = {
    "openai/gpt-oss-20b": (0.018, 0.09),
    "openai/gpt-oss-120b": (0.037, 0.17),
    "deepseek/deepseek-v4-flash": (0.079, 0.157),
    "qwen/qwen3.7-flash": (0.03, 0.13),
    "google/gemini-2.5-flash-lite": (0.10, 0.40),
    "anthropic/claude-sonnet-5": (2.0, 10.0),
    "anthropic/claude-sonnet-5.5": (2.0, 10.0),
}
UNKNOWN_PAID_PRICE = (3.0, 15.0)


def price_for(model_name: str) -> tuple[float, float]:
    return PRICES_PER_MILLION.get(model_name, UNKNOWN_PAID_PRICE)


def cost_usd(model_name: str, input_tokens: int, output_tokens: int) -> float:
    p_in, p_out = price_for(model_name)
    return (input_tokens * p_in + output_tokens * p_out) / 1_000_000


class SpendTracker:
    def __init__(self, path: Path | None = None, budget_usd: float | None = None) -> None:
        self.path = path or Path(os.environ.get("LLM_SPEND_FILE", Path(__file__).resolve().parent.parent / ".llm_spend.json"))
        self.budget_usd = budget_usd if budget_usd is not None else float(os.environ.get("LLM_BUDGET_USD", "4.5"))
        self._lock = threading.Lock()
        self._warned = False
        self._spent = self._load()
        self.calls = self.tokens_in = self.tokens_out = 0  # this process, all providers (free included)

    def _load(self) -> float:
        try:
            return float(json.loads(self.path.read_text()).get("spent_usd", 0.0))
        except (OSError, ValueError):
            return 0.0

    @property
    def spent_usd(self) -> float:
        return self._spent

    def note_usage(self, tokens_in: int, tokens_out: int) -> None:
        with self._lock:
            self.calls += 1
            self.tokens_in += tokens_in
            self.tokens_out += tokens_out

    def paid_allowed(self) -> bool:
        return self._spent < self.budget_usd

    def record(self, amount: float) -> None:
        with self._lock:
            self._spent += amount
            try:
                self.path.write_text(json.dumps({"spent_usd": round(self._spent, 6)}))
            except OSError:
                logger.warning("could not persist LLM spend to %s", self.path)
            if not self._warned and self._spent >= 0.8 * self.budget_usd:
                self._warned = True
                logger.warning("LLM spend $%.3f is at 80%% of the $%.2f budget", self._spent, self.budget_usd)

    def snapshot(self) -> dict[str, float | bool]:
        return {
            "spent_usd": round(self._spent, 4), "budget_usd": self.budget_usd, "paid_calls_enabled": self.paid_allowed(),
            "calls": self.calls, "tokens_in": self.tokens_in, "tokens_out": self.tokens_out,
        }


_tracker: SpendTracker | None = None


def get_tracker() -> SpendTracker:
    global _tracker
    if _tracker is None:
        _tracker = SpendTracker()
    return _tracker
