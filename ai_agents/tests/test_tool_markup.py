"""Raw model tool-call markup (DeepSeek's <｜DSML｜tool_calls>, harmony tokens, <tool_call> XML, bare JSON calls)
must never reach the chat UI, the stored transcript, or a later prompt.

The reported bug: a chain hop (DeepSeek) answered a fuel-receipt request with its native call syntax as plain text,
and it was streamed to the user and saved as the assistant's reply.
"""

from datetime import datetime, timedelta, timezone

import httpx
import jwt
import openai
import pytest
from langchain_core.messages import AIMessage

from core.llm_failover import FailoverChatModel, InvalidModelOutput, get_vision_chat_model, is_paid
from core.tool_markup import has_tool_markup, recover_tool_calls, strip_tool_markup
from memory.embeddings import NullEmbedder
from memory.service import AgentMemory
from orchestrator.graph import OrchestratorDeps
from orchestrator.sanitize_output import clean_response, sanitize_response
from orchestrator.session import TOOL_MARKUP_FALLBACK, OrchestratorSession
from tests.test_memory_units import FakeMemoryTools, InlineExecutor

BAR = "｜"  # the fullwidth bar DeepSeek's special tokens are written with


def _dsml(name="fuel", **params) -> str:
    inner = "".join(f'<{BAR}DSML{BAR}parameter name="{k}" string="true">{v}</{BAR}DSML{BAR}parameter>' for k, v in params.items())
    return f'<{BAR}DSML{BAR}tool_calls><{BAR}DSML{BAR}invoke name="{name}">{inner}</{BAR}DSML{BAR}invoke></{BAR}DSML{BAR}tool_calls>'


# The text from the bug report.
REPORTED = _dsml(query_entity="add_fill", vehicle_id="132415a0-8f72-47b0-9bf4-5bb093b8a9a9", liters="50", price_per_liter="280")


# --- the stripper -------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        (REPORTED, ""),
        (REPORTED.replace(BAR, "|"), ""),  # ASCII bars
        (f"I'll log that now.\n\n{REPORTED}\n\nDone.", "I'll log that now.\n\nDone."),
        (f'Sure. <{BAR}DSML{BAR}tool_calls><{BAR}DSML{BAR}invoke name="x">', "Sure."),  # cut off mid-call
        (f"ok <{BAR}tool▁calls▁begin{BAR}><{BAR}tool▁call▁begin{BAR}>function<{BAR}tool▁sep{BAR}>fuel\n```json\n{{}}\n```<{BAR}tool▁call▁end{BAR}><{BAR}tool▁calls▁end{BAR}> bye", "ok  bye"),
        ('Checking.<|start|>assistant<|channel|>commentary to=functions.fuel <|constrain|>json<|message|>{"q":1}<|call|>', "Checking."),
        ("<|channel|>final<|message|>The total is Rs 14,000.<|return|>", "The total is Rs 14,000."),
        ("<|channel|>analysis<|message|>hmm<|end|><|start|>assistant<|channel|>final<|message|>Answer.<|return|>", "Answer."),
        ('Logging. <tool_call>\n{"name": "fuel", "arguments": {"a": 1}}\n</tool_call>', "Logging."),
        ('x <function_calls><invoke name="fuel"><parameter name="a">1</parameter></invoke></function_calls> y', "x  y"),
        ('go <function=fuel>{"a": 1}</function> end', "go  end"),
        ('Here you go: {"name": "fuel", "arguments": {"query_entity": "fuel_logs"}}', "Here you go:"),
        ('[{"name":"a","arguments":{}},{"name":"b","arguments":{"x":1}}] ok', "ok"),
        ('Doing it.\n```json\n{"tool": "fuel", "args": {"q": 1}}\n```\n', "Doing it."),
        ('{"type": "function", "function": {"name": "fuel", "arguments": "{}"}}', ""),
    ],
    ids=["reported", "ascii-bars", "with-prose", "unclosed", "old-deepseek", "harmony-call", "harmony-final", "harmony-analysis",
         "qwen-xml", "anthropic-xml", "llama", "bare-json", "json-list", "fenced-json", "openai-shape"],
)
def test_raw_tool_markup_is_removed_and_the_words_around_it_survive(text, expected) -> None:
    assert strip_tool_markup(text) == expected
    assert has_tool_markup(text)


@pytest.mark.parametrize(
    "text",
    [
        "Total fuel: 155 Liters | Cost: Rs 43,500",
        "| Vehicle | Liters |\n|---|---|\n| AB-1234 | 50 |",
        'The API returns {"status": "ok", "count": 3}.',
        'Vehicle record: {"name": "Toyota Hilux", "year": 2022}',  # a name, but no arguments key: not a call
        "Use the <b>bold</b> tag or a list [1, 2, 3].",
        "We invoke the brakes; the function of this part is to stop.",
        "**Fuel & Cost Summary for Vehicle AB-1234**\n* **Total Fuel Consumed:** 155 Liters",
        "",
    ],
)
def test_ordinary_answers_pass_through_byte_for_byte(text) -> None:
    assert strip_tool_markup(text) == text
    assert not has_tool_markup(text)


def test_stripping_is_idempotent() -> None:
    once = strip_tool_markup(f"Hello {REPORTED} world")
    assert strip_tool_markup(once) == once == "Hello  world"


# --- the sanitizer that cleans synthesized text --------------------------------------------------


def test_the_response_sanitizer_removes_tool_markup_and_reports_it() -> None:
    cleaned = sanitize_response(f"Your fuel log is ready to confirm. {REPORTED}")
    assert cleaned.text == "Your fuel log is ready to confirm." and cleaned.leaked
    assert clean_response(REPORTED) == ""  # nothing but markup -> empty, so the caller regenerates


# --- failover: a hop that answers in raw call syntax has not answered ---------------------------


class _Hop:
    def __init__(self, name, reply=None, *, error=None):
        self.model_name, self.reply, self.error, self.calls = name, reply, error, 0

    def invoke(self, messages, **kwargs):
        self.calls += 1
        if self.error:
            raise self.error
        return self.reply


def _err(cls, status):
    return cls("boom", response=httpx.Response(status, request=httpx.Request("POST", "https://x/v1")), body=None)


def test_a_reply_made_of_raw_tool_markup_hands_over_to_the_next_model() -> None:
    deepseek = _Hop("deepseek", AIMessage(content=REPORTED))
    nemotron = _Hop("nemotron", AIMessage(content="Here is your fuel log."))

    result = FailoverChatModel(deepseek, nemotron).invoke("log it")

    assert result.content == "Here is your fuel log."
    assert (deepseek.calls, nemotron.calls) == (1, 1)


def test_when_every_model_leaks_markup_the_turn_fails_instead_of_showing_it() -> None:
    llm = FailoverChatModel(_Hop("a", AIMessage(content=REPORTED)), _Hop("b", AIMessage(content=f"x {REPORTED}")))
    with pytest.raises(InvalidModelOutput):  # nothing but markup, or markup with a couple of stray words
        llm.invoke("log it")


def test_a_plain_text_reply_with_real_words_beside_stray_markup_is_cleaned_not_rejected() -> None:
    """The last model in the chain wrote a summary and some tool syntax: the user gets the summary, not an error."""
    reply = AIMessage(content=f"The policy covers overtime approval and night shift allowances. {REPORTED}")
    only_model = _Hop("nemotron", reply)

    result = FailoverChatModel(only_model).invoke("summarize")

    assert result.content == "The policy covers overtime approval and night shift allowances."
    assert only_model.calls == 1


def test_the_same_cleaning_never_applies_when_tools_are_bound() -> None:
    """A planning reply with markup and words is not an answer to salvage: the call it held is recovered or it fails over."""
    garbled = _ToolHop("deepseek", AIMessage(content=f"Let me look that up for you right now. <{BAR}DSML{BAR}tool_calls><{BAR}DSML{BAR}invoke name="))
    good = _ToolHop("nemotron", AIMessage(content="Here you go."))

    reply = FailoverChatModel(garbled, good).bind_tools([]).invoke("x")

    assert reply.content == "Here you go." and good.calls == 1


# --- recovering the call the model meant to make -----------------------------------------------------


def _dsml_nested() -> str:
    return (
        f'<{BAR}DSML{BAR}tool_calls><{BAR}DSML{BAR}invoke name="fuel">'
        f'<{BAR}DSML{BAR}parameter name="document_type" string="true">receipt</{BAR}DSML{BAR}parameter>'
        f'<{BAR}DSML{BAR}parameter name="fuel_fields" string="false">{{"vehicle_id": "v1", "liters_filled": 50, "price_per_liter": 280}}</{BAR}DSML{BAR}parameter>'
        f"</{BAR}DSML{BAR}invoke></{BAR}DSML{BAR}tool_calls>"
    )


def test_a_call_written_out_as_dsml_is_recovered_with_its_nested_arguments_intact() -> None:
    (call,) = recover_tool_calls(f"Logging it. {_dsml_nested()}")

    assert call["name"] == "fuel" and call["type"] == "tool_call" and call["id"].startswith("call_")
    assert call["args"] == {"document_type": "receipt", "fuel_fields": {"vehicle_id": "v1", "liters_filled": 50, "price_per_liter": 280}}


def test_recovery_reads_typed_parameters_and_leaves_unreadable_ones_as_text() -> None:
    (call,) = recover_tool_calls(
        f'<{BAR}DSML{BAR}invoke name="x"><{BAR}DSML{BAR}parameter name="n" string="false">50</{BAR}DSML{BAR}parameter>'
        f'<{BAR}DSML{BAR}parameter name="flag" string="false">true</{BAR}DSML{BAR}parameter>'
        f'<{BAR}DSML{BAR}parameter name="s" string="true">50</{BAR}DSML{BAR}parameter>'
        f'<{BAR}DSML{BAR}parameter name="bad" string="false">{{oops</{BAR}DSML{BAR}parameter></{BAR}DSML{BAR}invoke>'
    )
    assert call["args"] == {"n": 50, "flag": True, "s": "50", "bad": "{oops"}


def test_recovery_understands_qwen_style_calls_and_skips_what_it_cannot_read() -> None:
    text = (
        '<tool_call>{"name": "fuel", "arguments": {"query_entity": "fuel_logs"}}</tool_call>'
        '<tool_call>{"name": "x", "arguments": "{\\"a\\": 1}"}</tool_call>'
        "<tool_call>not json</tool_call>"
        '<tool_call>{"arguments": {}}</tool_call>'
    )
    assert [(c["name"], c["args"]) for c in recover_tool_calls(text)] == [("fuel", {"query_entity": "fuel_logs"}), ("x", {"a": 1})]
    assert recover_tool_calls("plain answer") == [] and recover_tool_calls("") == []


class _ToolHop(_Hop):
    def bind_tools(self, tools, **kwargs):
        return self


def test_a_tool_bound_model_that_writes_its_call_as_text_still_makes_the_call() -> None:
    """The reported case: DeepSeek chose the fuel tool but printed the call. The backend runner gets a real call."""
    deepseek = _ToolHop("deepseek", AIMessage(content=f"Logging it. {_dsml_nested()}"))
    nemotron = _ToolHop("nemotron", AIMessage(content="never reached"))

    reply = FailoverChatModel(deepseek, nemotron).bind_tools([]).invoke("log it")

    assert [c["name"] for c in reply.tool_calls] == ["fuel"]
    assert reply.tool_calls[0]["args"]["fuel_fields"]["liters_filled"] == 50
    assert reply.content == "Logging it."  # nothing raw is left in the text
    assert (deepseek.calls, nemotron.calls) == (1, 0)  # no failover needed


def test_markup_that_holds_no_readable_call_still_fails_over_even_with_tools_bound() -> None:
    garbled = _ToolHop("deepseek", AIMessage(content=f'<{BAR}DSML{BAR}tool_calls><{BAR}DSML{BAR}invoke name="fuel">'))
    good = _ToolHop("nemotron", AIMessage(content="Here you go."))

    reply = FailoverChatModel(garbled, good).bind_tools([]).invoke("x")

    assert reply.content == "Here you go." and (garbled.calls, good.calls) == (1, 1)


def test_a_reply_without_tools_bound_is_never_turned_into_a_call() -> None:
    """Synthesis is plain text: a call written into it is junk to drop, not something to execute."""
    deepseek = _ToolHop("deepseek", AIMessage(content=_dsml_nested()))
    nemotron = _ToolHop("nemotron", AIMessage(content="Here you go."))

    assert FailoverChatModel(deepseek, nemotron).invoke("x").content == "Here you go."


# --- a reasoning model that spends its whole budget thinking ------------------------------------------


def test_a_reply_cut_off_by_the_token_limit_with_nothing_visible_hands_over_to_the_next_model() -> None:
    """DeepSeek under a 350-token planner cap: finish_reason=length, empty content, no tool call. Carrying on as if the
    model had nothing to do let the turn invent a result."""
    thinking = _Hop("deepseek", AIMessage(content="", response_metadata={"finish_reason": "length"}))
    good = _Hop("nemotron", AIMessage(content="Here you go."))

    assert FailoverChatModel(thinking, good).invoke("x").content == "Here you go."
    assert (thinking.calls, good.calls) == (1, 1)


@pytest.mark.parametrize(
    "reply",
    [
        AIMessage(content="A long answer that was cut o", response_metadata={"finish_reason": "length"}),  # partial text is still an answer
        AIMessage(content="", tool_calls=[{"name": "fuel", "args": {}, "id": "1", "type": "tool_call"}], response_metadata={"finish_reason": "length"}),
        AIMessage(content="", response_metadata={"finish_reason": "stop"}),  # an empty plan is a legitimate "no tool needed"
    ],
    ids=["partial-text", "tool-call", "empty-stop"],
)
def test_only_an_empty_truncated_reply_is_treated_as_unusable(reply) -> None:
    first, second = _Hop("a", reply), _Hop("b", AIMessage(content="other"))

    assert FailoverChatModel(first, second).invoke("x") is reply
    assert second.calls == 0


def test_deepseek_on_openrouter_is_asked_not_to_reason_unless_switched_on(monkeypatch) -> None:
    from core.llm_config import LLMProvider
    from core.llm_failover import _reasoning_kwargs

    monkeypatch.delenv("DEEPSEEK_REASONING", raising=False)
    assert _reasoning_kwargs(LLMProvider.CLAUDE_OPENROUTER, "deepseek/deepseek-v4-flash") == {"extra_body": {"reasoning": {"enabled": False}}}

    monkeypatch.setenv("DEEPSEEK_REASONING", "low")
    assert _reasoning_kwargs(LLMProvider.CLAUDE_OPENROUTER, "deepseek/deepseek-v4-flash") == {"extra_body": {"reasoning": {"effort": "low"}}}

    assert _reasoning_kwargs(LLMProvider.CLAUDE_OPENROUTER, "nvidia/nemotron-3.5-lightning:free") == {}  # other models untouched


class _StructuredHop(_Hop):
    def __init__(self, name, result=None, *, error=None):
        super().__init__(name, result, error=error)

    def with_structured_output(self, schema, **kwargs):
        return self  # invoke() returns the {"raw", "parsed", "parsing_error"} dict as-is


def test_structured_output_falls_over_on_errors_and_on_replies_that_do_not_parse() -> None:
    quota = _StructuredHop("groq", error=_err(openai.RateLimitError, 429))
    garbled = _StructuredHop("deepseek", {"raw": AIMessage(content=REPORTED), "parsed": None, "parsing_error": ValueError("no tool call")})
    good = _StructuredHop("gemini", {"raw": AIMessage(content=""), "parsed": {"liters": 50}, "parsing_error": None})

    llm = FailoverChatModel(quota, garbled, good)

    assert llm.with_structured_output(dict).invoke(["read this"]) == {"liters": 50}
    assert (quota.calls, garbled.calls, good.calls) == (1, 1, 1)
    assert llm.with_structured_output(dict).invoke(["again"]) == {"liters": 50}
    assert (quota.calls, good.calls) == (1, 2)  # the rate-limited hop is on cooldown; nobody re-asks it


def test_a_model_the_account_cannot_use_is_put_on_cooldown_not_retried_every_time() -> None:
    missing = _Hop("llama-4-scout", error=_err(openai.NotFoundError, 404))
    working = _Hop("qwen", "ok")
    llm = FailoverChatModel(missing, working)

    for _ in range(3):
        assert llm.invoke("x") == "ok"

    assert (missing.calls, working.calls) == (1, 3)


# --- the session: nothing with raw markup is saved or returned -----------------------------------


def _token() -> str:
    payload = {"sub": "user-1", "org": "org-1", "role": "admin", "exp": datetime.now(timezone.utc) + timedelta(minutes=30)}
    return jwt.encode(payload, "irrelevant-signing-key", algorithm="HS256")


class _LLM:
    def __init__(self, *replies):
        self._replies = list(replies)
        self.calls = 0

    def bind_tools(self, tools):
        return self

    def invoke(self, messages, **kwargs):
        self.calls += 1
        return self._replies.pop(0) if len(self._replies) > 1 else self._replies[0]


class _NoRunner:
    def run(self, *args, **kwargs):
        raise AssertionError("no sub-agent should run")


def _session(llm, tools=None):
    memory = AgentMemory(embedder=NullEmbedder(), tools=tools or FakeMemoryTools(), background=InlineExecutor())
    return OrchestratorSession(_token(), deps=OrchestratorDeps(llm=llm, runner=_NoRunner(), memory=memory))


def test_a_synthesis_made_only_of_markup_becomes_a_plain_apology_and_is_saved_that_way() -> None:
    tools = FakeMemoryTools()
    llm = _LLM(AIMessage(content=""), AIMessage(content=REPORTED))  # plan: no tool call; synthesis: raw markup, twice

    result = _session(llm, tools).run("Which vehicles do we have?")

    assert result.status == "done"
    assert result.final_response == "I couldn't produce a reliable answer to that. Please try rephrasing or asking again."
    saved = [content for role, content in tools.of("append") if role == "assistant"]
    assert saved == [result.final_response]
    assert BAR not in result.final_response and "DSML" not in result.final_response


def test_markup_beside_real_text_is_cut_out_before_it_is_returned_or_saved() -> None:
    tools = FakeMemoryTools()
    llm = _LLM(AIMessage(content=""), AIMessage(content=f"You have 12 vehicles. {REPORTED}"))

    result = _session(llm, tools).run("How many vehicles do we have?")

    assert result.final_response == "You have 12 vehicles."
    assert [c for r, c in tools.of("append") if r == "assistant"] == ["You have 12 vehicles."]


def test_the_final_choke_point_cleans_any_reply_even_one_an_earlier_layer_missed() -> None:
    tools = FakeMemoryTools()
    session = _session(_LLM(AIMessage(content="unused")), tools)

    settled = session._settle({**session.state, "stage": "done", "final_response": f"Approved. {REPORTED}"})
    assert settled.final_response == "Approved."
    assert settled.state["chat_history"][-1] == {"role": "assistant", "content": "Approved."}

    only = session._settle({**session.state, "stage": "done", "final_response": REPORTED})
    assert only.final_response == TOOL_MARKUP_FALLBACK
    assert [c for r, c in tools.of("append") if r == "assistant"] == ["Approved.", TOOL_MARKUP_FALLBACK]


def test_old_stored_replies_with_markup_are_not_fed_back_to_the_model_as_history() -> None:
    class _Poisoned(FakeMemoryTools):
        def get_session_context_tool(self, context, session_id, timeout=10.0):
            return {
                "session": {"running_summary": "", "summary_version": 0},
                "unsummarized_messages": [
                    {"id": "1", "role": "user", "content": "Log this fuel fill"},
                    {"id": "2", "role": "assistant", "content": REPORTED},
                    {"id": "3", "role": "user", "content": "Try again"},
                    {"id": "4", "role": "assistant", "content": f"Logged. {REPORTED}"},
                ],
            }

    memory = AgentMemory(embedder=NullEmbedder(), tools=_Poisoned(), background=InlineExecutor())
    session = OrchestratorSession(_token(), deps=OrchestratorDeps(llm=_LLM(AIMessage(content="x")), runner=_NoRunner(), memory=memory), memory_session_id="s-1")

    assert session.state["chat_history"] == [
        {"role": "user", "content": "Log this fuel fill"},
        {"role": "user", "content": "Try again"},
        {"role": "assistant", "content": "Logged."},
    ]


def test_the_stored_transcript_endpoint_hides_markup_in_old_messages() -> None:
    import server

    rows = [
        {"id": "1", "role": "user", "content": "Log this", "created_at": "2026-09-30T20:00:00Z"},
        {"id": "2", "role": "assistant", "content": REPORTED, "created_at": "2026-09-30T20:00:01Z"},
        {"id": "3", "role": "assistant", "content": f"Done. {REPORTED}", "created_at": "2026-09-30T20:00:02Z"},
    ]

    assert [(r["id"], r["content"]) for r in server._visible_messages(rows)] == [("1", "Log this"), ("3", "Done.")]


# --- the vision model chain ---------------------------------------------------------------------


@pytest.fixture
def vision_env(monkeypatch):
    for key in ("GROQ_API_KEY", "OPENROUTER_API_KEY", "OPEN_ROUTER_API_KEY", "GROQ_VISION_MODEL", "VISION_PAID_MODEL", "VISION_FREE_MODEL"):
        monkeypatch.delenv(key, raising=False)
    get_vision_chat_model.cache_clear()
    yield monkeypatch
    get_vision_chat_model.cache_clear()


def test_the_vision_chain_is_groq_then_a_cheap_paid_model_then_a_free_one(vision_env) -> None:
    import core.llm_failover as lf

    vision_env.setenv("GROQ_API_KEY", "k")
    vision_env.setenv("OPENROUTER_API_KEY", "k")

    chain = get_vision_chat_model()

    assert [lf._name(m) for m in chain.models] == ["qwen/qwen3.8-27b", "google/gemini-2.5-flash-lite", "qwen/qwen3.8-27b:free"]
    assert [is_paid(m) for m in chain.models] == [False, True, False]  # only the middle hop bills, and the budget breaker gates it
    assert all(m.max_tokens == 600 and m.max_retries == 0 for m in chain.models)  # Groq's qwen refuses a larger max_tokens outright
    assert chain.models[0].reasoning_effort == "none"  # qwen3 on Groq: skip hidden reasoning


def test_a_configured_groq_vision_model_goes_first_with_the_default_behind_it(vision_env) -> None:
    import core.llm_failover as lf

    vision_env.setenv("GROQ_API_KEY", "k")
    vision_env.setenv("GROQ_VISION_MODEL", "meta-llama/llama-4-scout-17b-16e-instruct")

    chain = get_vision_chat_model()

    assert [lf._name(m) for m in chain.models] == ["meta-llama/llama-4-scout-17b-16e-instruct", "qwen/qwen3.8-27b"]
    assert getattr(chain.models[0], "reasoning_effort", None) is None  # only qwen3 accepts that parameter


def test_the_vision_chain_is_shared_so_cooldowns_are_remembered(vision_env) -> None:
    vision_env.setenv("GROQ_API_KEY", "k")
    assert get_vision_chat_model() is get_vision_chat_model()


def test_with_no_provider_configured_extraction_fails_cleanly_not_with_a_crash(vision_env) -> None:
    from tools import file_parsers

    with pytest.raises(file_parsers.ExtractionFailedError, match="No vision model is configured"):
        file_parsers.extract_fuel_receipt(b"\x89PNG", "image/png")


def test_extraction_reads_the_photo_through_the_shared_chain(monkeypatch) -> None:
    from tools import file_parsers
    from tools.schemas import FuelReceiptExtraction

    seen = {}

    class _Chain:
        def with_structured_output(self, schema):
            seen["schema"] = schema
            return self

        def invoke(self, messages):
            seen["content"] = messages[0].content
            return FuelReceiptExtraction(liters=50, total_cost=14000)

    monkeypatch.setattr(file_parsers, "get_vision_model", lambda: _Chain())

    result = file_parsers.extract_fuel_receipt(b"\x89PNG", "image/png")

    assert (result.liters, result.total_cost) == (50, 14000) and seen["schema"] is FuelReceiptExtraction
    assert seen["content"][1]["image_url"]["url"].startswith("data:image/png;base64,")


def test_a_structured_reply_cut_off_mid_json_hands_over_to_the_next_model() -> None:
    from pydantic import BaseModel, ValidationError

    class Receipt(BaseModel):
        station: str

    try:
        Receipt.model_validate_json('{\n  "station_')
    except ValidationError as exc:
        truncated = exc
    cut_off = _StructuredHop("qwen", error=truncated)
    good = _StructuredHop("gemini", {"raw": AIMessage(content=""), "parsed": {"station": "PGL"}, "parsing_error": None})

    llm = FailoverChatModel(cut_off, good)

    assert llm.with_structured_output(dict).invoke(["read this"]) == {"station": "PGL"}
    assert (cut_off.calls, good.calls) == (1, 1)
