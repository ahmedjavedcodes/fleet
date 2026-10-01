"""Multi-provider chat models: an ordered chain, OpenRouter first, then Groq.

The orchestrator, fact-checker and memory summarizer all run through this, so a provider
outage, an exhausted quota (Groq's free tier caps tokens per day) or an empty credit balance
degrades to the next model instead of failing the user's turn.

Default chain (an optional local Ollama tier goes in front):
  OpenRouter deepseek-v4-flash   primary: $0.08/$0.16 per M, ~3 s, 10 s timeout (budget-gated)
  Groq gpt-oss-20b       free, ~1 s, 4 s timeout           }  backup; each Groq model has its OWN daily
  Groq gpt-oss-120b      free, ~1.3 s, 4 s timeout         }  quota, so one running dry isn't an outage
  a free OpenRouter model        last resort, 8 s timeout
Claude (premium) is opt-in only (OPENROUTER_PREMIUM_MODEL / ORCHESTRATOR_PROVIDER=openrouter).
If every model fails the caller can still answer plain reads deterministically
(orchestrator/offline.py) before showing an error.

Paid models are gated by the budget circuit-breaker (core/llm_budget.py), and every call logs
tokens, cost and latency. Timeouts are short and SDK retries are off, so a slow or throttled
provider is abandoned in seconds and the next tier answers.

Which errors move down the chain: any `openai.APIError` -- rate limits, 402 out-of-credits,
5xx, timeouts, connection failures, a rejected/malformed tool call (another model often gets
it right), even a bad key. Anything else (a bug in our own code) propagates untouched.

A model that answered 402/429, or could not be reached at all (a local Ollama that isn't
running), is skipped for a short cooldown, so a quota that stays exhausted for 20 minutes
costs one probe a minute, not one wasted request per turn.
"""

from __future__ import annotations

import logging
import os
import re
import threading
import time
from functools import lru_cache
from typing import Any, Callable

import openai
from langchain_core.exceptions import OutputParserException
from pydantic import ValidationError

import httpx

from core.llm_budget import cost_usd, get_tracker
from core.llm_config import LLMProvider, get_chat_model
from core.tool_markup import has_tool_markup, recover_tool_calls, strip_tool_markup

logger = logging.getLogger("fleet.llm")
if not logger.handlers:  # per-call telemetry (tokens, cost, latency) must be visible under uvicorn too
    _handler = logging.StreamHandler()
    _handler.setFormatter(logging.Formatter("%(levelname)s:     [llm] %(message)s"))
    logger.addHandler(_handler)
    logger.setLevel(logging.INFO)
    logger.propagate = False

COOLDOWN_SECONDS = 60.0  # default when the provider gives no retry hint
MAX_COOLDOWN_SECONDS = 3600.0
_COOLDOWN_STATUS = (402, 404, 429)  # 404: "model does not exist or you do not have access" -- stop re-asking every turn
_RETRY_HINT = re.compile(r"try again in (?:(\d+)h)?(?:(\d+)m)?(?:([\d.]+)s)?", re.IGNORECASE)
_FAILOVER_ERRORS = (openai.APIError,)
DEFAULT_FREE_OPENROUTER_MODEL = "nvidia/nemotron-3.5-lightning:free"
DEFAULT_CHEAP_OPENROUTER_MODEL = "deepseek/deepseek-v4-flash"
DEFAULT_GROQ_SECOND_MODEL = "openai/gpt-oss-120b"
DEFAULT_OLLAMA_MODEL = "qwen2.5:1.5b-instruct"
# Per-provider timeouts (SDK retries are off): a slow provider is abandoned, then the next runs.
GROQ_TIMEOUT_SECONDS = float(os.environ.get("GROQ_TIMEOUT_SECONDS", "4"))
OPENROUTER_TIMEOUT_SECONDS = float(os.environ.get("OPENROUTER_TIMEOUT_SECONDS", "10"))
FREE_TIMEOUT_SECONDS = float(os.environ.get("FREE_TIMEOUT_SECONDS", "8"))
OLLAMA_TIMEOUT_SECONDS = float(os.environ.get("OLLAMA_TIMEOUT_SECONDS", "1.5"))
OLLAMA_PROBE_TIMEOUT_SECONDS = 1.0
GUARD_TIMEOUT_SECONDS = float(os.environ.get("GUARD_TIMEOUT_SECONDS", "0.8"))
# A dedicated classification model, not the planner's gpt-oss-20b: Groq meters quota per model, so the guard's
# ~400 tokens per message never eat into the planner's daily budget, and it answers in ~150-200 ms (vs ~400-700).
DEFAULT_GUARD_MODEL = "openai/gpt-oss-safeguard-20b"
# Vision (photo -> structured record). Groq's qwen3.8-27b reads images and answers a receipt in ~1-2 s; it caps
# OUTPUT at 1,000 tokens a minute, so a request's max_tokens must stay well under that or it is refused outright.
DEFAULT_VISION_GROQ_MODEL = "qwen/qwen3.8-27b"
DEFAULT_VISION_PAID_MODEL = "google/gemini-2.5-flash-lite"  # ~$0.0002 per receipt; the reliable last resort
DEFAULT_VISION_FREE_MODEL = "qwen/qwen3.8-27b:free"
VISION_TIMEOUT_SECONDS = float(os.environ.get("VISION_TIMEOUT_SECONDS", "25"))
VISION_MAX_TOKENS = int(os.environ.get("VISION_MAX_TOKENS", "600"))


class BudgetExhausted(RuntimeError):
    """The spend cap was reached and no free model is configured."""


def _cooldown_seconds(exc: BaseException) -> float:
    """How long to skip a model after it failed: the provider's own Retry-After header or
    "try again in 19m7s" hint when it gives one, else a short default."""
    retry: float | None = None
    response = getattr(exc, "response", None)
    try:
        retry = float(response.headers.get("retry-after")) if response is not None else None
    except (TypeError, ValueError, AttributeError):
        retry = None
    if retry is None:
        match = _RETRY_HINT.search(str(exc))
        if match and any(match.groups()):
            hours, minutes, seconds = match.groups()
            retry = int(hours or 0) * 3600 + int(minutes or 0) * 60 + float(seconds or 0)
    if retry is None:
        retry = 300.0 if getattr(exc, "status_code", None) == 402 else COOLDOWN_SECONDS
    return min(max(retry, 5.0), MAX_COOLDOWN_SECONDS)


def _reasoning_kwargs(provider: LLMProvider, model: str) -> dict[str, Any]:
    """gpt-oss models spend most of their output budget on hidden reasoning (measured: ~100 of
    ~170 tokens for a two-sentence answer). "low" cut that to ~5, made replies ~60% smaller and
    stopped a tight max_tokens cap from leaving the visible answer empty."""
    if provider is LLMProvider.CLAUDE_OPENROUTER and model.startswith("deepseek/"):
        # DeepSeek V4 reasons by default. Under the planner's 350-token and the reply's 500-token caps the thinking
        # alone used the whole budget (finish_reason=length, empty content, no tool call), so the turn carried on as if
        # the model had nothing to do and then made up a result. Planning and replying need no chain of thought.
        # DEEPSEEK_REASONING=low|medium|high turns it back on.
        setting = os.environ.get("DEEPSEEK_REASONING", "off").strip().lower()
        return {"extra_body": {"reasoning": {"enabled": False} if setting in ("", "off", "0", "false", "none") else {"effort": setting}}}
    effort = os.environ.get("LLM_REASONING_EFFORT", "low").strip()
    if not effort or "gpt-oss" not in model:
        return {}
    if provider is LLMProvider.GROQ:
        return {"reasoning_effort": effort}
    return {"extra_body": {"reasoning": {"effort": effort}}}  # OpenRouter's spelling


class InvalidModelOutput(RuntimeError):
    """A 200 response that is not a usable answer."""


MARKUP_LEAK = "raw tool-call markup leaked into the reply"


def _invalid_output(result: Any) -> str | None:
    """Some hosted models return HTTP 200 with finish_reason "error" and nothing in it, or leak their
    raw internal tool-call format as the visible text instead of a structured tool call (gpt-oss
    harmony tokens, DeepSeek's <｜DSML｜tool_calls>, <tool_call> XML ...; the provider is supposed to
    parse it server-side and some don't). Neither is an answer: try the next model.

    A structured-output result ({"raw", "parsed", "parsing_error"}) is also unusable when it did not
    parse into the requested schema."""
    if isinstance(result, dict) and "parsed" in result:
        if result["parsed"] is None:
            return "reply did not parse into the requested schema"
        result = result.get("raw")
    meta = getattr(result, "response_metadata", None) or {}
    if meta.get("finish_reason") == "error":
        return "provider returned finish_reason=error"
    content = getattr(result, "content", "")
    if isinstance(content, str) and has_tool_markup(content):
        return MARKUP_LEAK
    if meta.get("finish_reason") == "length" and not content and not getattr(result, "tool_calls", None):
        return "hit the token limit with nothing visible (hidden reasoning used the whole budget)"
    return None


def _with_recovered_tool_calls(result: Any, model: str) -> Any:
    """A model that was offered tools but wrote its call out as raw text (DeepSeek's <｜DSML｜tool_calls> ...)
    did decide to call the tool; only the transport is wrong. Rebuild the reply as the proper tool call it was
    meant to be, with the raw syntax removed from the text. The arguments are validated downstream like any other
    call, and write tools still wait for the user's approval."""
    content = getattr(result, "content", None)
    if getattr(result, "tool_calls", None) or not isinstance(content, str) or not has_tool_markup(content):
        return result
    calls = recover_tool_calls(content)
    if not calls:
        return result
    logger.warning("LLM %s wrote %d tool call(s) as raw text; recovered them as structured calls", model, len(calls))
    return result.model_copy(update={"content": strip_tool_markup(content), "tool_calls": calls})


def is_paid(model: Any) -> bool:
    """OpenRouter models without a :free suffix bill per token; Groq's free tier and local
    models do not."""
    return "openrouter.ai" in str(getattr(model, "openai_api_base", "")) and not _name(model).endswith(":free")


def openrouter_api_key() -> str | None:
    return os.environ.get("OPENROUTER_API_KEY") or os.environ.get("OPEN_ROUTER_API_KEY")


def _name(model: Any) -> str:
    return getattr(model, "model_name", "?")


class FailoverChatModel:
    """Quacks like the slice of a LangChain chat model the orchestrator uses:
    `invoke`, `bind_tools` and `model_name`."""

    accepts_max_tokens = True  # invoke(..., max_tokens=N) caps that call's output

    def __init__(self, primary: Any, *fallbacks: Any | None, clock: Callable[[], float] = time.monotonic) -> None:
        self.models = [primary, *[m for m in fallbacks if m is not None]]
        self._clock = clock
        self._blocked_until = [0.0] * len(self.models)
        self._stats: list[dict[str, Any]] = [{"calls": 0, "failures": 0, "tokens_in": 0, "tokens_out": 0, "last_error": None} for _ in self.models]
        self._lock = threading.Lock()
        self.last_model: str = _name(primary)

    @property
    def primary(self) -> Any:
        return self.models[0]

    @property
    def fallback(self) -> Any | None:
        return self.models[1] if len(self.models) > 1 else None

    @property
    def model_name(self) -> str:
        """The model that answered most recently (what telemetry should record)."""
        return self.last_model

    def invoke(self, messages: Any, **kwargs: Any) -> Any:
        return self._run(self.models, lambda model: model.invoke(messages, **kwargs))

    def status(self) -> list[dict[str, Any]]:
        """Each model's live state, for /health."""
        now = self._clock()
        rows = []
        for i, model in enumerate(self.models):
            wait = max(0.0, self._blocked_until[i] - now)
            rows.append({
                "model": _name(model), "paid": is_paid(model),
                "state": "cooling_down" if wait else "ready", "retry_in_seconds": round(wait),
                **self._stats[i],
            })
        return rows

    def bind_tools(self, tools: Any, **kwargs: Any) -> "_BoundFailover":
        return _BoundFailover(self, [m.bind_tools(tools, **kwargs) for m in self.models])

    def with_structured_output(self, schema: Any, **kwargs: Any) -> "_StructuredFailover":
        """Like a LangChain chat model's, but a hop that errors, is rate-limited, or answers in a shape that
        does not parse into `schema` hands over to the next model. Returns the parsed object."""
        return _StructuredFailover(self, [m.with_structured_output(schema, include_raw=True, **kwargs) for m in self.models])

    def _run(self, runnables: list[Any], call: Callable[[Any], Any], *, recover_calls: bool = False, extra_errors: tuple[type[BaseException], ...] = ()) -> Any:
        now = self._clock()
        budget_open = get_tracker().paid_allowed()
        allowed = [i for i in range(len(runnables)) if budget_open or not is_paid(self.models[i])]
        order = [i for i in allowed if now >= self._blocked_until[i]]
        if not order:  # everything is cooling down: better to probe again than to refuse
            order = allowed
        if not order:
            raise BudgetExhausted("LLM budget exhausted and no free model is configured")

        last_error: BaseException | None = None
        for position, i in enumerate(order):
            started = self._clock()
            try:
                result = call(runnables[i])
            except (*_FAILOVER_ERRORS, *extra_errors) as exc:
                last_error = exc
                unreachable = isinstance(exc, (openai.APIConnectionError, openai.APITimeoutError))
                self._stats[i]["failures"] += 1
                self._stats[i]["last_error"] = type(exc).__name__
                if unreachable or getattr(exc, "status_code", None) in _COOLDOWN_STATUS:
                    with self._lock:
                        # Only THIS model is skipped: a Groq 429 never blocks OpenRouter or vice versa.
                        self._blocked_until[i] = self._clock() + _cooldown_seconds(exc)
                following = order[position + 1] if position + 1 < len(order) else None
                detail = " ".join(str(getattr(exc, "message", None) or exc).split())[:180]
                logger.warning(
                    "LLM %s failed (%s: %s)%s", _name(self.models[i]), type(exc).__name__, detail,
                    f"; failing over to {_name(self.models[following])}" if following is not None else "; no models left",
                )
                continue
            self._account(self.models[i], result, self._clock() - started, i)  # a bad reply still cost tokens
            if recover_calls:
                result = _with_recovered_tool_calls(result, _name(self.models[i]))
            problem = _invalid_output(result)
            if problem == MARKUP_LEAK and not recover_calls:
                # A plain-text reply (no tools involved) that holds real words beside the stray markup is cleaned, not
                # thrown away: failing the turn over a few stray tokens would leave the user with an error.
                cleaned = strip_tool_markup(result.content)
                if len(cleaned) >= 20 and len(cleaned.split()) >= 4:  # real prose, not two stray words
                    logger.warning("LLM %s wrote raw tool-call markup beside its reply; removed it", _name(self.models[i]))
                    result, problem = result.model_copy(update={"content": cleaned}), None
            if problem:
                last_error = InvalidModelOutput(f"{_name(self.models[i])}: {problem}")
                self._stats[i]["failures"] += 1
                self._stats[i]["last_error"] = "InvalidModelOutput"
                logger.warning("LLM %s gave an unusable reply (%s)", _name(self.models[i]), problem)
                continue
            self.last_model = _name(self.models[i])
            return result
        assert last_error is not None
        raise last_error


    def _account(self, model: Any, result: Any, seconds: float, index: int = 0) -> None:
        """One log line per LLM call: model, tokens, cost, latency -- and paid spend recorded."""
        if isinstance(result, dict) and "raw" in result:  # a structured-output result: usage lives on the raw message
            result = result["raw"]
        usage = getattr(result, "usage_metadata", None) or {}
        tokens_in, tokens_out = int(usage.get("input_tokens", 0)), int(usage.get("output_tokens", 0))
        paid = is_paid(model)
        stats = self._stats[index]
        stats["calls"] += 1
        stats["tokens_in"] += tokens_in
        stats["tokens_out"] += tokens_out
        get_tracker().note_usage(tokens_in, tokens_out)
        cost = cost_usd(_name(model), tokens_in, tokens_out) if paid else 0.0
        if paid:
            get_tracker().record(cost)
        logger.info(
            "llm call model=%s tier=%s in=%d out=%d cost=$%.6f latency=%dms",
            _name(model), "paid" if paid else "free", tokens_in, tokens_out, cost, int(seconds * 1000),
        )


class _BoundFailover:
    accepts_max_tokens = True

    def __init__(self, parent: FailoverChatModel, bound: list[Any]) -> None:
        self._parent, self._bound = parent, bound

    def invoke(self, messages: Any, **kwargs: Any) -> Any:
        return self._parent._run(self._bound, lambda model: model.invoke(messages, **kwargs), recover_calls=True)


class _StructuredFailover:
    def __init__(self, parent: FailoverChatModel, bound: list[Any]) -> None:
        self._parent, self._bound = parent, bound

    def invoke(self, messages: Any, **kwargs: Any) -> Any:
        # A reply cut off mid-JSON surfaces as a parse error, not an API error: that hop failed, try the next.
        result = self._parent._run(
            self._bound, lambda model: model.invoke(messages, **kwargs), extra_errors=(ValidationError, OutputParserException)
        )
        return result["parsed"]


def _ollama_model() -> str | None:
    """The local model to use, or None. A 1 s probe of Ollama's model list: if it isn't
    running (or the wanted model isn't pulled) the tier is skipped silently -- never an error."""
    base = os.environ.get("LOCAL_LLM_BASE_URL", "http://localhost:11434/v1")
    wanted = os.environ.get("OLLAMA_PLANNER_MODEL", DEFAULT_OLLAMA_MODEL).strip()
    if not wanted:
        return None
    try:
        tags = httpx.get(base.rsplit("/v1", 1)[0] + "/api/tags", timeout=OLLAMA_PROBE_TIMEOUT_SECONDS).json()["models"]
    except Exception:  # noqa: BLE001 -- not running / not reachable / not JSON: bypass instantly
        return None
    installed = {m.get("name", "") for m in tags}
    return wanted if wanted in installed or f"{wanted}:latest" in installed else None


def get_resilient_chat_model(*, groq_model: str, claude_only: bool = False, **overrides: Any) -> Any:
    """The tiered chain described in the module docstring, each hop with its own timeout.

    claude_only uses the premium model alone (the orchestrator sets it from
    ORCHESTRATOR_PROVIDER=openrouter). Without an OpenRouter key the chain is just Groq.
    Environment: OLLAMA_PLANNER_MODEL, GROQ_SECOND_MODEL, OPENROUTER_CHEAP_MODEL,
    OPENROUTER_PREMIUM_MODEL, OPENROUTER_FREE_MODEL."""
    overrides.setdefault("max_retries", 0)  # fail over immediately instead of backing off inside the SDK
    has_openrouter = bool(openrouter_api_key())
    chain: list[Any] = []

    def add(provider: LLMProvider, timeout: float, **kwargs: Any) -> None:
        chain.append(get_chat_model(provider, **kwargs, **{**overrides, "timeout": timeout}))

    if claude_only and has_openrouter:
        premium = os.environ.get("OPENROUTER_PREMIUM_MODEL", "").strip()
        add(LLMProvider.CLAUDE_OPENROUTER, OPENROUTER_TIMEOUT_SECONDS, **({"model": premium} if premium else {}))
    else:
        local = _ollama_model()
        if local:
            add(LLMProvider.LOCAL_LLAMA, OLLAMA_TIMEOUT_SECONDS, model=local)
        # OpenRouter is the primary (budget-gated by core/llm_budget.py); the free Groq models are the backup.
        if has_openrouter:
            cheap = os.environ.get("OPENROUTER_CHEAP_MODEL", DEFAULT_CHEAP_OPENROUTER_MODEL).strip()
            add(LLMProvider.CLAUDE_OPENROUTER, OPENROUTER_TIMEOUT_SECONDS, model=cheap, **_reasoning_kwargs(LLMProvider.CLAUDE_OPENROUTER, cheap))
        add(LLMProvider.GROQ, GROQ_TIMEOUT_SECONDS, model=groq_model, **_reasoning_kwargs(LLMProvider.GROQ, groq_model))
        second = os.environ.get("GROQ_SECOND_MODEL", DEFAULT_GROQ_SECOND_MODEL).strip()
        if second and second != groq_model:
            add(LLMProvider.GROQ, GROQ_TIMEOUT_SECONDS, model=second, **_reasoning_kwargs(LLMProvider.GROQ, second))
    if has_openrouter:
        free = os.environ.get("OPENROUTER_FREE_MODEL", DEFAULT_FREE_OPENROUTER_MODEL).strip()
        if free:
            add(LLMProvider.CLAUDE_OPENROUTER, FREE_TIMEOUT_SECONDS, model=free)
    return FailoverChatModel(*chain)


def get_guard_chat_model(timeout: float = GUARD_TIMEOUT_SECONDS) -> Any | None:
    """The small, fast chain behind the semantic input guard (orchestrator/security.py), or None if it can't be built.

    Tier 0 local Ollama when it is running, then Groq gpt-oss-safeguard-20b (GUARD_MODEL overrides) -- and
    deliberately nothing else: no second Groq model and no paid OpenRouter tier, because the guard runs on every message and
    must be both fast and free. Each hop's HTTP timeout is the guard's own budget, so a slow hop is abandoned
    within that time rather than lingering. When the guard can't answer, the caller falls back to keywords."""
    chain: list[Any] = []
    try:
        local = _ollama_model()
        if local:
            chain.append(get_chat_model(LLMProvider.LOCAL_LLAMA, model=local, max_retries=0, timeout=timeout))
        if os.environ.get("GROQ_API_KEY"):
            model = os.environ.get("GUARD_MODEL", DEFAULT_GUARD_MODEL).strip() or DEFAULT_GUARD_MODEL
            chain.append(get_chat_model(LLMProvider.GROQ, model=model, max_retries=0, timeout=timeout, **_reasoning_kwargs(LLMProvider.GROQ, model)))
    except Exception:  # noqa: BLE001 -- a guard that can't start means "keywords only", never a failed startup
        logger.exception("LLM guard model could not be built; the keyword allowlist will be used")
        return None
    return FailoverChatModel(*chain) if chain else None


@lru_cache(maxsize=1)
def get_vision_chat_model() -> FailoverChatModel:
    """The shared chain behind every photo/text -> structured-record extraction (tools/file_parsers.py).

    Groq first (GROQ_VISION_MODEL, default qwen3.8-27b -- fast and free), then, when an OpenRouter key exists, a
    cheap paid vision model (VISION_PAID_MODEL, gated by the budget breaker) and a free one. One shared instance,
    so a hop that is rate-limited or not enabled for the account is skipped for its cooldown instead of being
    retried by every upload. `with_structured_output` hands a hop over when it errors OR answers in a shape that
    does not parse into the schema."""
    timeout, max_tokens = VISION_TIMEOUT_SECONDS, VISION_MAX_TOKENS
    chain: list[Any] = []

    def groq(model: str) -> None:
        extra = {"reasoning_effort": os.environ.get("VISION_REASONING_EFFORT", "none")} if "qwen3" in model else {}
        chain.append(get_chat_model(LLMProvider.GROQ, model=model, max_tokens=max_tokens, timeout=timeout, max_retries=0, **extra))

    def openrouter(model: str) -> None:
        chain.append(get_chat_model(LLMProvider.CLAUDE_OPENROUTER, model=model, max_tokens=max_tokens, timeout=timeout, max_retries=0))

    if os.environ.get("GROQ_API_KEY"):
        configured = os.environ.get("GROQ_VISION_MODEL", "").strip() or DEFAULT_VISION_GROQ_MODEL
        groq(configured)
        if configured != DEFAULT_VISION_GROQ_MODEL:
            groq(DEFAULT_VISION_GROQ_MODEL)
    if openrouter_api_key():
        openrouter(os.environ.get("VISION_PAID_MODEL", "").strip() or DEFAULT_VISION_PAID_MODEL)
        free = os.environ.get("VISION_FREE_MODEL", DEFAULT_VISION_FREE_MODEL).strip()
        if free:
            openrouter(free)
    if not chain:
        raise RuntimeError("No vision model is configured: set GROQ_API_KEY or OPENROUTER_API_KEY")
    return FailoverChatModel(*chain)

