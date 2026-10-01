"""Token diet: compact tool results, short history, a stable cacheable prefix, and routing the final reply separately."""

import json
from datetime import datetime, timedelta, timezone

import jwt
import pytest
import tiktoken
from langchain_core.messages import AIMessage

from orchestrator import graph as g
from orchestrator.compaction import cap_text, compact, render_result, shorten_turn
from orchestrator.graph import HISTORY_WINDOW, OrchestratorDeps, _format_observation, _history_to_messages
from orchestrator.runner import RunResult
from orchestrator.session import OrchestratorSession

ENC = tiktoken.get_encoding("cl100k_base")


def tokens(text) -> int:
    return len(ENC.encode(text if isinstance(text, str) else json.dumps(text)))


VEHICLE = {"id": "132415a0-8f72", "plate_number": "AB-1234", "make": "Toyota", "model": "Hilux", "vin": "CHS-99887766", "status": "active",
           "service_interval_km": None, "service_interval_months": None, "added_by": "", "created_at": "2026-01-01", "organization_id": "o1", "tags": []}


def test_empty_fields_and_bookkeeping_are_dropped_but_answers_are_kept() -> None:
    assert compact(VEHICLE) == {"id": "132415a0-8f72", "plate_number": "AB-1234", "make": "Toyota", "model": "Hilux", "vin": "CHS-99887766", "status": "active"}
    assert compact({"a": 0, "b": False}) == {"a": 0, "b": False}  # zero and false are values, not blanks


def test_a_long_list_is_cut_between_records_and_says_how_many_were_left_out() -> None:
    rows = [{**VEHICLE, "plate_number": f"AB-{1000 + i}"} for i in range(60)]

    text = render_result("query_result", rows)

    assert tokens(text) <= 1_100  # budget is 800 estimated at ~4 chars/token; id-heavy JSON tokenizes denser
    assert text.startswith("query_result=[{") and "AB-1000" in text
    left_out = int(text.split("...[")[1].split(" more of")[0])
    assert 0 < left_out < 60 and "more of 60 records" in text
    json.loads(text[len("query_result="): text.index(" ...[")])  # what was kept is still valid JSON: no half record


def test_a_small_result_is_not_marked_as_cut() -> None:
    assert "cut" not in render_result("query_result", [VEHICLE]) and "not shown" not in render_result("query_result", [VEHICLE])


def test_a_big_scalar_result_is_capped() -> None:
    text = render_result("fleet_health", {"notes": "x" * 20_000})

    assert tokens(text) < 900 and "more characters" in text
    assert cap_text("short") == "short"


def test_the_observation_the_model_reads_is_the_compact_one() -> None:
    result = RunResult(status="done", state={"query_result": [VEHICLE] * 40}, thread_id="t")

    observation = _format_observation("foundation", result)

    assert observation.startswith("foundation succeeded: query_result=[") and tokens(observation) < 1_100
    assert "service_interval_km" not in observation and "created_at" not in observation


def test_an_earlier_long_turn_is_shortened_but_the_last_two_messages_stay_whole() -> None:
    long_old, long_new = "old " * 400, "new " * 400
    state = {"chat_history": [{"role": "user", "content": long_old}, {"role": "assistant", "content": long_old},
                              {"role": "user", "content": long_new}, {"role": "assistant", "content": long_new}]}

    messages = _history_to_messages(state)

    contents = [str(m.content) for m in messages[1:]]
    assert contents[0].endswith("[earlier message shortened]") and len(contents[0]) < 760
    assert contents[2] == long_new and contents[3] == long_new
    assert shorten_turn("fine") == "fine"


def _token() -> str:
    return jwt.encode({"sub": "u", "org": "o", "role": "admin", "exp": datetime.now(timezone.utc) + timedelta(minutes=30)}, "k", algorithm="HS256")


class _LLM:
    def __init__(self, *responses):
        self.responses, self.seen = list(responses), []

    def bind_tools(self, tools):
        return self

    def invoke(self, messages, **kwargs):
        self.seen.append(messages)
        return self.responses.pop(0) if len(self.responses) > 1 else self.responses[0]


class _NoRunner:
    def run(self, *a, **k):
        raise AssertionError


def test_the_in_process_history_is_a_sliding_window() -> None:
    session = OrchestratorSession(_token(), deps=OrchestratorDeps(llm=_LLM(AIMessage(content="ok")), runner=_NoRunner()))

    for i in range(20):
        session.run(f"How many vehicles do we have, question {i}?")

    assert len(session.state["chat_history"]) <= 2 * HISTORY_WINDOW + 1  # the window going in, plus the reply just added


def test_the_planner_sees_at_most_the_window_of_messages() -> None:
    llm = _LLM(AIMessage(content="ok"))
    session = OrchestratorSession(_token(), deps=OrchestratorDeps(llm=llm, runner=_NoRunner()))
    for i in range(12):
        session.run(f"How many vehicles do we have, question {i}?")

    human = [m for m in llm.seen[-1] if m.type in ("human", "ai")]
    assert len(human) <= HISTORY_WINDOW + 1  # the window, plus the question being asked


# --- prompt caching ------------------------------------------------------------------------------


def test_the_static_prefix_comes_first_and_is_a_plain_string_for_providers_that_cache_automatically(monkeypatch) -> None:
    for var in ("LLM_PROMPT_CACHE", "ORCHESTRATOR_PROVIDER", "OPENROUTER_PREMIUM_MODEL"):
        monkeypatch.delenv(var, raising=False)

    messages = _history_to_messages({"chat_history": [{"role": "user", "content": "hi"}], "memory_context": "likes PKR"}, documents_enabled=True)

    assert messages[0].type == "system" and isinstance(messages[0].content, str) and "Grand Orchestrator" in messages[0].content
    assert "likes PKR" in str(messages[1].content)  # per-turn material only after the static prompt


@pytest.mark.parametrize(
    ("env", "expected"),
    [
        ({"ORCHESTRATOR_PROVIDER": "openrouter", "OPENROUTER_PREMIUM_MODEL": "anthropic/claude-sonnet-5"}, True),
        ({"ORCHESTRATOR_PROVIDER": "openrouter", "OPENROUTER_PREMIUM_MODEL": "deepseek/deepseek-v4-pro"}, False),
        ({}, False),
        ({"LLM_PROMPT_CACHE": "on"}, True),
        ({"LLM_PROMPT_CACHE": "off", "ORCHESTRATOR_PROVIDER": "openrouter", "OPENROUTER_PREMIUM_MODEL": "anthropic/claude-sonnet-5"}, False),
    ],
)
def test_anthropic_models_get_an_explicit_cache_marker_on_the_static_system_prompt(monkeypatch, env, expected) -> None:
    for var in ("LLM_PROMPT_CACHE", "ORCHESTRATOR_PROVIDER", "OPENROUTER_PREMIUM_MODEL"):
        monkeypatch.delenv(var, raising=False)
    for key, value in env.items():
        monkeypatch.setenv(key, value)

    system = _history_to_messages({"chat_history": []})[0]

    if expected:
        assert system.content[0]["cache_control"] == {"type": "ephemeral"} and "Grand Orchestrator" in system.content[0]["text"]
    else:
        assert isinstance(system.content, str)


# --- routing -------------------------------------------------------------------------------------


def test_a_separate_synthesis_model_writes_the_reply_while_the_planner_stays_on_the_cheap_chain() -> None:
    planner = _LLM(AIMessage(content=""))
    writer = _LLM(AIMessage(content="There are 12 vehicles."))
    session = OrchestratorSession(_token(), deps=OrchestratorDeps(llm=planner, runner=_NoRunner(), synthesis_llm=writer))

    result = session.run("How many vehicles do we have?")

    assert result.final_response == "There are 12 vehicles."
    assert len(planner.seen) == 1 and len(writer.seen) == 1  # one planning call, one reply call


def test_without_a_synthesis_model_the_same_chain_does_both(monkeypatch) -> None:
    monkeypatch.delenv("SYNTHESIS_PREMIUM_MODEL", raising=False)
    g.get_synthesis_llm.cache_clear()

    assert g.get_synthesis_llm() is None
    llm = _LLM(AIMessage(content=""), AIMessage(content="Twelve."))
    result = OrchestratorSession(_token(), deps=OrchestratorDeps(llm=llm, runner=_NoRunner())).run("How many vehicles do we have?")
    assert result.final_response == "Twelve."


def test_a_premium_synthesis_model_sits_in_front_of_the_cheap_chain(monkeypatch) -> None:
    monkeypatch.setenv("SYNTHESIS_PREMIUM_MODEL", "anthropic/claude-sonnet-5")
    monkeypatch.setenv("OPENROUTER_API_KEY", "k")
    monkeypatch.setenv("GROQ_API_KEY", "k")
    g.get_synthesis_llm.cache_clear()
    g.get_shared_llm.cache_clear()
    try:
        llm = g.get_synthesis_llm()
        assert llm.models[0].model_name == "anthropic/claude-sonnet-5" and len(llm.models) > 1
    finally:
        g.get_synthesis_llm.cache_clear()
        g.get_shared_llm.cache_clear()


# --- the budget ----------------------------------------------------------------------------------


def test_the_fixed_part_of_every_planning_call_stays_small() -> None:
    from langchain_core.utils.function_calling import convert_to_openai_tool

    from orchestrator.tools import build_llm_tools

    tool_tokens = tokens([convert_to_openai_tool(t)["function"] for t in build_llm_tools(include_memory=True, include_documents=True)])
    fixed = tokens(g._SYSTEM_PROMPT) + tokens(g._DOCUMENT_TOOL_PROMPT) + tool_tokens

    assert tool_tokens < 2_700, tool_tokens  # was 3,195 before compression
    assert fixed < 3_200, fixed  # was 3,710
