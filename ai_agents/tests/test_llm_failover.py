import httpx
import openai
import pytest

from core.llm_failover import COOLDOWN_SECONDS, FailoverChatModel, get_resilient_chat_model, is_paid, openrouter_api_key


def _err(cls, status):
    response = httpx.Response(status, request=httpx.Request("POST", "https://x/v1/chat/completions"))
    return cls("boom", response=response, body=None)


class _Model:
    def __init__(self, name, *, error=None, reply="ok"):
        self.model_name, self.error, self.reply = name, error, reply
        self.calls, self.bound_with = 0, None

    def invoke(self, messages, **kw):
        self.calls += 1
        if self.error:
            raise self.error
        return f"{self.reply} from {self.model_name}"

    def bind_tools(self, tools, **kw):
        self.bound_with = tools
        return self


class _Clock:
    def __init__(self):
        self.now = 1000.0

    def __call__(self):
        return self.now


def test_the_primary_answers_when_healthy_and_the_fallback_is_untouched() -> None:
    groq, claude = _Model("gpt-oss"), _Model("claude")
    llm = FailoverChatModel(groq, claude)
    assert llm.invoke("hi") == "ok from gpt-oss"
    assert (groq.calls, claude.calls, llm.model_name) == (1, 0, "gpt-oss")


@pytest.mark.parametrize(
    "error",
    [_err(openai.RateLimitError, 429), _err(openai.InternalServerError, 500), _err(openai.BadRequestError, 400), _err(openai.AuthenticationError, 401),
     openai.APIConnectionError(request=httpx.Request("POST", "https://x")), openai.APITimeoutError(request=httpx.Request("POST", "https://x"))],
)
def test_any_provider_error_fails_over_to_claude(error) -> None:
    groq, claude = _Model("gpt-oss", error=error), _Model("claude")
    llm = FailoverChatModel(groq, claude)
    assert llm.invoke("hi") == "ok from claude"
    assert llm.model_name == "claude"  # telemetry records who actually answered


def test_a_bug_in_our_own_code_is_not_swallowed_by_failover() -> None:
    llm = FailoverChatModel(_Model("gpt-oss", error=ValueError("our bug")), _Model("claude"))
    with pytest.raises(ValueError):
        llm.invoke("hi")


def test_a_rate_limited_primary_is_skipped_for_the_cooldown_then_probed_again() -> None:
    clock = _Clock()
    groq, claude = _Model("gpt-oss", error=_err(openai.RateLimitError, 429)), _Model("claude")
    llm = FailoverChatModel(groq, claude, clock=clock)

    llm.invoke("a")
    llm.invoke("b")
    llm.invoke("c")
    assert (groq.calls, claude.calls) == (1, 3)  # only the first turn paid for a doomed Groq call

    clock.now += COOLDOWN_SECONDS + 1
    groq.error = None  # quota window rolled over
    assert llm.invoke("d") == "ok from gpt-oss"


def test_a_non_rate_limit_error_does_not_start_a_cooldown() -> None:
    groq, claude = _Model("gpt-oss", error=_err(openai.InternalServerError, 500)), _Model("claude")
    llm = FailoverChatModel(groq, claude)
    llm.invoke("a")
    llm.invoke("b")
    assert groq.calls == 2  # a transient 5xx: try the primary again next turn


def test_bound_tools_fail_over_too_and_both_models_get_the_tools() -> None:
    groq, claude = _Model("gpt-oss", error=_err(openai.RateLimitError, 429)), _Model("claude")
    bound = FailoverChatModel(groq, claude).bind_tools(["tool-a"])
    assert bound.invoke("hi") == "ok from claude"
    assert groq.bound_with == ["tool-a"] and claude.bound_with == ["tool-a"]


def test_without_a_fallback_the_primary_error_propagates() -> None:
    llm = FailoverChatModel(_Model("gpt-oss", error=_err(openai.RateLimitError, 429)), None)
    with pytest.raises(openai.RateLimitError):
        llm.invoke("hi")


def test_both_providers_failing_raises_the_fallbacks_error() -> None:
    llm = FailoverChatModel(_Model("gpt-oss", error=_err(openai.RateLimitError, 429)), _Model("claude", error=_err(openai.InternalServerError, 500)))
    with pytest.raises(openai.InternalServerError):
        llm.invoke("hi")


# --- construction from the environment ------------------------------------------------


def test_both_spellings_of_the_openrouter_key_are_accepted(monkeypatch) -> None:
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    monkeypatch.setenv("OPEN_ROUTER_API_KEY", "sk-or-test")
    assert openrouter_api_key() == "sk-or-test"


def test_default_chain_is_openrouter_first_then_two_free_groq_models_then_a_free_model(monkeypatch) -> None:
    import core.llm_failover as lf

    monkeypatch.setenv("GROQ_API_KEY", "gsk-test")
    monkeypatch.setenv("OPEN_ROUTER_API_KEY", "sk-or-test")
    for var in ("OPENROUTER_CHEAP_MODEL", "OPENROUTER_PREMIUM_MODEL", "OPENROUTER_FREE_MODEL", "GROQ_SECOND_MODEL"):
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setattr(lf, "_ollama_model", lambda: None)
    llm = get_resilient_chat_model(groq_model="openai/gpt-oss-20b")
    assert [m.model_name for m in llm.models] == [
        "deepseek/deepseek-v4-flash", "openai/gpt-oss-20b", "openai/gpt-oss-120b", "nvidia/nemotron-3.5-lightning:free",
    ]
    assert [is_paid(m) for m in llm.models] == [True, False, False, False]  # only the DeepSeek hop can spend money
    assert not any("claude" in m.model_name for m in llm.models)
    # Tailored per-provider timeouts, and no SDK-internal retries so failover is immediate.
    assert [m.request_timeout for m in llm.models] == [10, 4, 4, 8]
    assert all(m.max_retries == 0 for m in llm.models)

    monkeypatch.setenv("OPENROUTER_FREE_MODEL", "")  # empty disables the free last resort
    assert len(get_resilient_chat_model(groq_model="openai/gpt-oss-20b").models) == 3


def test_an_optional_local_ollama_tier_goes_first_with_a_1_5s_timeout(monkeypatch) -> None:
    import core.llm_failover as lf

    monkeypatch.setenv("GROQ_API_KEY", "gsk-test")
    monkeypatch.delenv("OPEN_ROUTER_API_KEY", raising=False)
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    monkeypatch.setattr(lf, "_ollama_model", lambda: "qwen2.5:1.5b-instruct")
    llm = get_resilient_chat_model(groq_model="openai/gpt-oss-20b")
    assert [m.model_name for m in llm.models][:2] == ["qwen2.5:1.5b-instruct", "openai/gpt-oss-20b"]
    assert llm.primary.request_timeout == 1.5 and not is_paid(llm.primary)


def test_ollama_that_is_not_running_is_bypassed_instantly_without_raising(monkeypatch) -> None:
    import core.llm_failover as lf

    seen = {}

    def refuse(url, timeout):
        seen["timeout"] = timeout
        raise httpx.ConnectError("connection refused")

    monkeypatch.setattr(lf.httpx, "get", refuse)
    assert lf._ollama_model() is None
    assert seen["timeout"] == 1.0  # the probe itself is capped at 1 s


def test_ollama_is_used_only_when_the_wanted_model_is_actually_pulled(monkeypatch) -> None:
    import core.llm_failover as lf

    class _Tags:
        def __init__(self, names):
            self._names = names

        def json(self):
            return {"models": [{"name": n} for n in self._names]}

    monkeypatch.delenv("OLLAMA_PLANNER_MODEL", raising=False)
    monkeypatch.setattr(lf.httpx, "get", lambda url, timeout: _Tags(["llama3.2:1b", "qwen2.5:1.5b-instruct"]))
    assert lf._ollama_model() == "qwen2.5:1.5b-instruct"  # the documented default
    monkeypatch.setenv("OLLAMA_PLANNER_MODEL", "llama3.2:1b")
    assert lf._ollama_model() == "llama3.2:1b"
    monkeypatch.setenv("OLLAMA_PLANNER_MODEL", "not-pulled:7b")
    assert lf._ollama_model() is None
    monkeypatch.setenv("OLLAMA_PLANNER_MODEL", "")
    assert lf._ollama_model() is None  # explicitly disabled


def test_claude_only_and_no_key_variants(monkeypatch) -> None:
    import core.llm_failover as lf

    monkeypatch.setattr(lf, "_ollama_model", lambda: None)
    monkeypatch.setenv("GROQ_API_KEY", "gsk-test")
    monkeypatch.setenv("OPEN_ROUTER_API_KEY", "sk-or-test")
    solo = get_resilient_chat_model(groq_model="openai/gpt-oss-20b", claude_only=True)
    assert all("openrouter.ai" in str(m.openai_api_base) for m in solo.models) and "claude" in solo.primary.model_name

    monkeypatch.delenv("OPEN_ROUTER_API_KEY")
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    groq_only = get_resilient_chat_model(groq_model="openai/gpt-oss-20b")
    assert [m.model_name for m in groq_only.models] == ["openai/gpt-oss-20b", "openai/gpt-oss-120b"]  # two Groq quotas, no OpenRouter


def test_openrouter_requests_cap_their_output_so_a_small_credit_balance_is_enough(monkeypatch) -> None:
    monkeypatch.setenv("OPEN_ROUTER_API_KEY", "sk-or-test")
    monkeypatch.delenv("OPENROUTER_MAX_TOKENS", raising=False)
    from core.llm_config import LLMProvider, get_chat_model

    assert get_chat_model(LLMProvider.CLAUDE_OPENROUTER).max_tokens == 1500
    monkeypatch.setenv("OPENROUTER_MAX_TOKENS", "800")
    assert get_chat_model(LLMProvider.CLAUDE_OPENROUTER).max_tokens == 800


def test_the_chain_walks_past_an_out_of_credits_claude_to_the_free_model_and_remembers_it() -> None:
    clock = _Clock()
    groq = _Model("gpt-oss", error=_err(openai.RateLimitError, 429))
    claude = _Model("claude", error=_err(openai.APIStatusError, 402))
    free = _Model("free-model")
    llm = FailoverChatModel(groq, claude, free, clock=clock)

    assert llm.invoke("a") == "ok from free-model" and llm.model_name == "free-model"
    assert llm.invoke("b") == "ok from free-model"
    assert (groq.calls, claude.calls, free.calls) == (1, 1, 2)  # 429 and 402 both start a cooldown

    clock.now += 301  # a 402 (no credit) is retried after 5 minutes, not every minute
    claude.error = None  # credits added
    assert llm.invoke("c") == "ok from claude"  # the better model is preferred again once it recovers


def test_when_every_model_is_cooling_down_the_chain_still_tries_rather_than_refusing() -> None:
    clock = _Clock()
    a, b = _Model("a", error=_err(openai.RateLimitError, 429)), _Model("b", error=_err(openai.RateLimitError, 429))
    llm = FailoverChatModel(a, b, clock=clock)
    with pytest.raises(openai.RateLimitError):
        llm.invoke("1")
    a.error = None
    assert llm.invoke("2") == "ok from a"


# --- budget circuit-breaker and per-call accounting -------------------------------------


def _paid_model(name="openai/gpt-oss-20b", *, tokens=(1000, 100), error=None):
    from langchain_core.messages import AIMessage

    class _P(_Model):
        openai_api_base = "https://openrouter.ai/api/v1"

        def invoke(self, messages, **kw):
            self.calls += 1
            if self.error:
                raise self.error
            return AIMessage(content="ok", usage_metadata={"input_tokens": tokens[0], "output_tokens": tokens[1], "total_tokens": sum(tokens)})

    return _P(name, error=error)


@pytest.fixture()
def tracker(tmp_path, monkeypatch):
    from core import llm_budget

    t = llm_budget.SpendTracker(path=tmp_path / "spend.json", budget_usd=0.001)
    monkeypatch.setattr(llm_budget, "_tracker", t)
    return t


def test_paid_calls_are_costed_from_token_usage_and_persisted(tracker, tmp_path) -> None:
    from core.llm_budget import SpendTracker, cost_usd

    llm = FailoverChatModel(_paid_model(tokens=(10_000, 1_000)))
    llm.invoke("hi")
    expected = cost_usd("openai/gpt-oss-20b", 10_000, 1_000)  # $0.00027
    assert expected == pytest.approx(0.00027) and tracker.spent_usd == pytest.approx(expected)
    assert SpendTracker(path=tmp_path / "spend.json").spent_usd == pytest.approx(expected)  # survives a restart


def test_free_models_never_spend_or_trip_the_breaker(tracker) -> None:
    llm = FailoverChatModel(_Model("groq-free"))
    llm.invoke("hi")
    assert tracker.spent_usd == 0


def test_once_the_budget_is_spent_paid_models_are_skipped_and_free_ones_carry_on(tracker) -> None:
    paid, free = _paid_model(tokens=(10_000, 1_000)), _Model("free-model")
    llm = FailoverChatModel(_Model("groq", error=_err(openai.RateLimitError, 429)), paid, free)
    llm.invoke("a")  # spends $0.00027 of the $0.001 budget
    llm.invoke("b")
    llm.invoke("c")
    llm.invoke("d")  # crosses it
    assert not tracker.paid_allowed()
    paid_calls = paid.calls
    assert llm.invoke("e") == "ok from free-model"
    assert paid.calls == paid_calls  # the breaker held: no paid request was made


def test_with_only_paid_models_left_an_exhausted_budget_stops_the_call() -> None:
    from core import llm_budget

    llm_budget._tracker = llm_budget.SpendTracker(budget_usd=0.0)
    try:
        with pytest.raises(RuntimeError, match="budget exhausted"):
            FailoverChatModel(_paid_model()).invoke("hi")
    finally:
        llm_budget._tracker = None


def test_an_unreachable_local_model_costs_one_timeout_then_is_skipped(tracker) -> None:
    clock = _Clock()
    down = _Model("ollama", error=openai.APIConnectionError(request=httpx.Request("POST", "http://localhost:11434")))
    llm = FailoverChatModel(down, _Model("groq"), clock=clock)
    for _ in range(4):
        llm.invoke("hi")
    assert down.calls == 1  # not retried every turn


def test_max_tokens_is_passed_through_to_the_real_chain_only() -> None:
    seen = {}

    class _Capturing(_Model):
        def invoke(self, messages, **kw):
            seen.update(kw)
            return "ok"

    FailoverChatModel(_Capturing("m")).invoke("hi", max_tokens=250)
    assert seen == {"max_tokens": 250}
    assert FailoverChatModel.accepts_max_tokens is True


def test_gpt_oss_models_run_at_low_reasoning_effort_on_both_providers(monkeypatch) -> None:
    import core.llm_failover as lf

    monkeypatch.setenv("GROQ_API_KEY", "gsk-test")
    monkeypatch.setenv("OPEN_ROUTER_API_KEY", "sk-or-test")
    monkeypatch.setenv("OPENROUTER_CHEAP_MODEL", "openai/gpt-oss-20b")
    monkeypatch.delenv("LLM_REASONING_EFFORT", raising=False)
    monkeypatch.setattr(lf, "_ollama_model", lambda: None)
    cheap, groq20, groq120, free = get_resilient_chat_model(groq_model="openai/gpt-oss-20b").models
    assert groq20.reasoning_effort == "low" and groq120.reasoning_effort == "low"
    assert cheap.extra_body == {"reasoning": {"effort": "low"}}  # OpenRouter's spelling of the same knob
    assert free.extra_body is None  # not a gpt-oss model: no such parameter

    monkeypatch.setenv("LLM_REASONING_EFFORT", "")
    assert get_resilient_chat_model(groq_model="openai/gpt-oss-20b").models[1].reasoning_effort is None


def _reply(content="ok", finish="stop"):
    from langchain_core.messages import AIMessage

    return AIMessage(content=content, response_metadata={"finish_reason": finish})


class _Scripted(_Model):
    def __init__(self, name, reply):
        super().__init__(name)
        self._reply_value = reply

    def invoke(self, messages, **kw):
        self.calls += 1
        return self._reply_value


@pytest.mark.parametrize(
    "bad",
    [_reply("", finish="error"), _reply("<|start|>assistant<|channel|>commentary to=foundation <|call|>"), _reply("x <|channel|> y")],
)
def test_a_200_with_an_error_finish_or_leaked_tool_markup_fails_over(bad) -> None:
    broken, good = _Scripted("provider-a", bad), _Scripted("provider-b", _reply("The answer."))
    llm = FailoverChatModel(broken, good)
    assert llm.invoke("hi").content == "The answer."
    assert llm.model_name == "provider-b"


def test_a_legitimately_empty_planner_stop_is_not_treated_as_broken() -> None:
    only = _Scripted("m", _reply("", finish="stop"))  # "no more tool calls" is a valid planner outcome
    assert FailoverChatModel(only).invoke("hi").content == ""


def test_if_every_model_gives_unusable_output_the_turn_errors_instead_of_showing_markup() -> None:
    from core.llm_failover import InvalidModelOutput

    llm = FailoverChatModel(_Scripted("a", _reply("<|call|>")), _Scripted("b", _reply("", finish="error")))
    with pytest.raises(InvalidModelOutput):
        llm.invoke("hi")


def test_an_unusable_paid_reply_is_still_billed(tracker) -> None:
    from langchain_core.messages import AIMessage

    class _BadPaid(_Model):
        openai_api_base = "https://openrouter.ai/api/v1"

        def invoke(self, messages, **kw):
            return AIMessage(content="", response_metadata={"finish_reason": "error"}, usage_metadata={"input_tokens": 10_000, "output_tokens": 0, "total_tokens": 10_000})

    FailoverChatModel(_BadPaid("openai/gpt-oss-20b"), _Scripted("free", _reply("fine"))).invoke("hi")
    assert tracker.spent_usd > 0
