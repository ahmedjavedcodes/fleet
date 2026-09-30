"""The unreachable-cascade fix: independent per-model cooldowns driven by the provider's own
retry hint, the deterministic no-LLM fallback, the shared model chain, prompt/token budgets and
the /health report."""

from datetime import date, datetime, timedelta, timezone

import httpx
import jwt
import openai
import pytest
from langchain_core.messages import AIMessage

from core import llm_budget
from core.llm_failover import FailoverChatModel, InvalidModelOutput, _cooldown_seconds


def _err(cls, status, *, headers=None, message="boom"):
    response = httpx.Response(status, headers=headers or {}, request=httpx.Request("POST", "https://x/v1/chat/completions"))
    return cls(message, response=response, body=None)


class _Model:
    def __init__(self, name, *, error=None):
        self.model_name, self.error, self.calls = name, error, 0

    def invoke(self, messages, **kw):
        self.calls += 1
        if self.error:
            raise self.error
        return AIMessage(content=f"ok from {self.model_name}", usage_metadata={"input_tokens": 100, "output_tokens": 10, "total_tokens": 110})

    def bind_tools(self, tools, **kw):
        return self


class _Clock:
    now = 1000.0

    def __call__(self):
        return self.now


@pytest.fixture(autouse=True)
def _isolated_tracker(tmp_path, monkeypatch):
    monkeypatch.setattr(llm_budget, "_tracker", llm_budget.SpendTracker(path=tmp_path / "spend.json", budget_usd=5))


# --- cooldowns come from the provider, and never spill across providers -------------------


@pytest.mark.parametrize(
    ("exc", "seconds"),
    [
        (_err(openai.RateLimitError, 429, headers={"retry-after": "90"}), 90),
        (_err(openai.RateLimitError, 429, message="Please try again in 19m7.824s. Need more tokens?"), 19 * 60 + 7.824),
        (_err(openai.RateLimitError, 429, message="try again in 45m3s"), 2703),
        (_err(openai.RateLimitError, 429), 60),  # no hint: the short default
        (_err(openai.APIStatusError, 402), 300),  # out of credit: don't hammer it
        (_err(openai.RateLimitError, 429, headers={"retry-after": "1"}), 5),  # floor
        (_err(openai.RateLimitError, 429, headers={"retry-after": "999999"}), 3600),  # ceiling
    ],
)
def test_cooldown_follows_the_providers_retry_hint(exc, seconds) -> None:
    assert _cooldown_seconds(exc) == pytest.approx(seconds)


def test_a_rate_limited_groq_never_locks_out_openrouter_and_vice_versa() -> None:
    clock = _Clock()
    groq = _Model("groq", error=_err(openai.RateLimitError, 429, headers={"retry-after": "1200"}))
    router = _Model("openrouter")
    llm = FailoverChatModel(groq, router, clock=clock)

    assert llm.invoke("a").content == "ok from openrouter"
    rows = {r["model"]: r for r in llm.status()}
    assert rows["groq"]["state"] == "cooling_down" and rows["groq"]["retry_in_seconds"] == 1200
    assert rows["openrouter"]["state"] == "ready"  # only the rate-limited model is skipped

    router.error = openai.APITimeoutError(request=httpx.Request("POST", "https://x"))
    with pytest.raises(openai.APITimeoutError):
        llm.invoke("b")  # OpenRouter times out while Groq is still cooling down
    rows = {r["model"]: r for r in llm.status()}
    assert rows["openrouter"]["state"] == "cooling_down" and rows["openrouter"]["retry_in_seconds"] == 60
    assert rows["groq"]["retry_in_seconds"] == 1200  # each model keeps its own clock

    clock.now += 61
    router.error = None
    assert llm.invoke("c").content == "ok from openrouter"  # OpenRouter is back after ITS cooldown, Groq still out


def test_status_reports_per_model_calls_tokens_and_the_last_error() -> None:
    groq = _Model("groq", error=_err(openai.InternalServerError, 500))
    llm = FailoverChatModel(groq, _Model("router"))
    llm.invoke("a")
    llm.invoke("b")
    groq_row, router_row = llm.status()
    assert (groq_row["failures"], groq_row["last_error"], groq_row["state"]) == (2, "InternalServerError", "ready")  # 5xx: no cooldown
    assert (router_row["calls"], router_row["tokens_in"], router_row["tokens_out"]) == (2, 200, 20)
    usage = llm_budget.get_tracker().snapshot()
    assert (usage["calls"], usage["tokens_in"], usage["tokens_out"]) == (2, 200, 20)


# --- the deterministic no-LLM fallback --------------------------------------------------------


from agents.fuel.summary import summarize_fuel  # noqa: E402
from orchestrator.offline import FOOTNOTE, answer_offline, format_fallback_response, plan_offline_read  # noqa: E402
from orchestrator.runner import RunResult  # noqa: E402

TODAY = date(2026, 9, 30)


class _Runner:
    def __init__(self, data=None, status="done", halt=None):
        self.data, self.status, self.halt, self.calls = data, status, halt, []

    def run(self, agent, state, *, thread_id=None):
        self.calls.append((agent, {k: v for k, v in state.items() if k != "token"}))
        return RunResult(status=self.status, state={"query_result": self.data, "halt_reason": self.halt}, thread_id="t")


@pytest.mark.parametrize(
    ("message", "agent", "entity"),
    [
        ("Which vehicles are due for service?", "maintenance", "service_due"),
        ("What is overdue for servicing?", "maintenance", "service_due"),
        ("Show low stock parts", "maintenance", "low_stock"),
        ("How many parts are in inventory?", "maintenance", "inventory"),
        ("Show me the maintenance history", "maintenance", "maintenance_logs"),
        ("Show the fuel logs", "fuel", "fuel_logs"),
        ("List recent trips", "fuel", "trip_logs"),
        ("How many severe incidents this month?", "accountability", "incidents"),
        ("What is the fleet health?", "insights", "fleet_health"),
        ("Show the dashboard summary", "insights", "dashboard_summary"),
        ("List all drivers", "foundation", "drivers"),
        ("Which vehicles do we have?", "foundation", "vehicles"),
    ],
)
def test_plain_reads_map_to_one_read_only_sub_agent_query(message, agent, entity) -> None:
    plan = plan_offline_read(message)
    assert (plan.agent, plan.args["query_entity"]) == (agent, entity)


@pytest.mark.parametrize(
    ("message", "args"),
    [
        ("Show me the total fuel consumed and average cost per kilometer for vehicle AB-1234 over the last month.", {"query_plate": "AB-1234", "query_days": 30}),
        ("What was our total fuel cost?", {}),
        ("Show the fuel logs for AB-1234", {"query_plate": "AB-1234"}),
        ("How much did we spend on fuel in the past 14 days?", {"query_days": 14}),
        ("Show the fuel cost for the last week", {"query_days": 7}),
        ("Show me the total fuel used by ab-1234", {"query_plate": "AB-1234"}),
        ("What is the average cost per km?", {}),
    ],
)
def test_fuel_totals_questions_ask_the_deterministic_summary_for_the_right_vehicle_and_period(message, args) -> None:
    plan = plan_offline_read(message)
    assert (plan.agent, plan.args) == ("fuel", {"query_entity": "fuel_summary", **args})


@pytest.mark.parametrize(
    "message",
    ["Log a trip for ABC-123", "Assign ABC-123 to Jane", "Remember I prefer PKR", "Update the odometer for AB-1234", "Hello there", ""],
)
def test_writes_memory_changes_and_unmatched_messages_are_never_answered_offline(message) -> None:
    assert plan_offline_read(message) is None


FUEL_LOGS = [
    {"vehicle_plate": "AB-1234", "date": "2026-09-05", "liters_filled": "60.0", "total_cost": "16800", "odometer_reading": 45000, "vin": "SECRET"},
    {"vehicle_plate": "AB-1234", "date": "2026-09-14", "liters_filled": "50.0", "total_cost": "14000", "odometer_reading": 45500},
    {"vehicle_plate": "AB-1234", "date": "2026-09-27", "liters_filled": "45.0", "total_cost": "12700", "odometer_reading": 46000},
    {"vehicle_plate": "AB-1234", "date": "2026-07-01", "liters_filled": "50", "total_cost": "14000", "odometer_reading": 30000},  # outside the month
    {"vehicle_plate": "CD-5678", "date": "2026-09-20", "liters_filled": "10", "total_cost": "2800", "odometer_reading": 1000},  # another vehicle
]
FUEL_QUESTION = "Show me the total fuel consumed and average cost per kilometer for vehicle AB-1234 over the last month."
FUEL_SUMMARY = summarize_fuel(FUEL_LOGS, plate="AB-1234", days=30, today=TODAY)  # what the fuel agent's fuel_summary query returns


def test_the_fuel_question_gets_the_clean_computed_summary_not_a_log_dump() -> None:
    runner = _Runner(FUEL_SUMMARY)
    text = answer_offline(FUEL_QUESTION, runner, "tok")

    assert runner.calls == [("fuel", {"query_entity": "fuel_summary", "query_plate": "AB-1234", "query_days": 30})]  # a read, and only that
    assert text == (
        "**Fuel & Cost Summary for Vehicle AB-1234 (Past Month)**\n"
        "* **Total Fuel Consumed:** 155 Liters\n"
        "* **Total Fuel Cost:** Rs 43,500\n"
        "* **Total Distance Covered:** 1,000 km (45,000 km → 46,000 km)\n"
        "* **Average Cost per km:** Rs 43.50 / km\n\n"
        f"{FOOTNOTE}"
    )
    for leaked in ("vehicle_plate", "odometer_reading", "liters_filled", "SECRET", "=", "The AI model is unavailable"):
        assert leaked not in text


def test_fuel_summary_is_honest_when_distance_cannot_be_computed_or_there_is_no_data() -> None:
    text = format_fallback_response("fuel_summary", summarize_fuel([FUEL_LOGS[0]], plate="AB-1234", today=TODAY))
    assert "not available (needs at least two fills)" in text and "Average Cost per km:** not available" in text

    empty = format_fallback_response("fuel_summary", summarize_fuel([], plate="CD-5678", days=30, today=TODAY))
    assert "No fuel logs recorded for this period." in empty and "Rs 0" not in empty
    assert empty.endswith(FOOTNOTE)


def test_a_plain_fuel_log_request_still_lists_rows_and_never_computes_totals() -> None:
    runner = _Runner([FUEL_LOGS[1]])
    text = answer_offline("Show the fuel logs", runner, "tok")

    assert runner.calls == [("fuel", {"query_entity": "fuel_logs"})]
    assert "**AB-1234**" in text and "Total Fuel Consumed" not in text


def test_service_due_renders_readable_lines_without_ids_or_field_names() -> None:
    data = {
        "overdue": [{"plate_number": "ABC-123", "service_type": "oil_change", "km_remaining": -250, "next_due_date": "2026-09-01", "vehicle_id": "hidden"}],
        "upcoming": [{"plate_number": "DEF-456", "service_type": "brake_service", "km_remaining": 800}],
    }
    text = answer_offline("Which vehicles are due for service?", _Runner(data), "tok")
    assert "**Overdue service (1)**\n* **ABC-123** — Oil change · 250 km overdue · by 1 Sep 2026" in text
    assert "**Upcoming service (1)**\n* **DEF-456** — Brake service · due in 800 km" in text
    for leaked in ("plate_number", "service_type", "km_remaining", "vehicle_id", "hidden", "="):
        assert leaked not in text


@pytest.mark.parametrize(
    ("entity", "row", "expected"),
    [
        ("vehicles", {"plate_number": "AB-1234", "make": "Toyota", "model": "Hilux", "status": "active", "current_odometer": 46000, "vin": "V1N"}, "**AB-1234** — Toyota Hilux · Active · 46,000 km"),
        ("drivers", {"full_name": "Sara Khan", "status": "active", "license_expiry": "2030-01-12"}, "**Sara Khan** — Active · licence expires 12 Jan 2030"),
        ("inventory", {"name": "Brake Pad", "part_number": "BP-1", "qty_on_hand": 3, "reorder_threshold": 5}, "**Brake Pad** (BP-1) — 3 in stock · reorder at 5"),
        ("maintenance_logs", {"vehicle_plate": "AB-1234", "date": "2026-01-05", "service_types": ["oil_change", "brake_service"], "cost": "8000"}, "**AB-1234** (5 Jan 2026) — Oil change, Brake service · Rs 8,000"),
        ("incidents", {"vehicle_plate": "AB-1234", "date": "2026-09-29", "incident_type": "damage", "severity": "severe", "resolution_status": "open", "description": "Bumper"}, "**AB-1234** (29 Sep 2026) — Damage · **severe** · Open · Bumper"),
        ("fleet_health", {"plate_number": "AB-1234", "health_score": 76}, "**AB-1234** — health score 76/100"),
    ],
)
def test_each_record_type_renders_as_one_readable_markdown_bullet(entity, row, expected) -> None:
    text = format_fallback_response(entity, [row])
    assert f"* {expected}" in text
    assert "V1N" not in text and "_id" not in text


def test_dashboard_summary_and_unknown_records_use_human_labels() -> None:
    text = format_fallback_response("dashboard_summary", {"total_vehicles": 11, "active_drivers": 5, "month_fuel_cost": "120000.0000", "open_incidents_count": 0})
    assert "* **Vehicles:** 11" in text and "* **Fuel cost this month:** Rs 120,000" in text and "* **Open incidents:** 0" in text

    generic = format_fallback_response("something_new", [{"id": "x", "supplier_id": "y", "lead_time": 4, "notes": "on_hold"}])
    assert "Lead time: 4, Notes: On hold" in generic and "supplier_id" not in generic


def test_long_lists_are_truncated_and_a_refused_lookup_is_explained() -> None:
    many = [{"plate_number": f"AA-{n:04d}", "make": "Toyota", "model": "Hilux"} for n in range(1000, 1020)]
    text = answer_offline("Which vehicles do we have?", _Runner(many), "tok")
    assert "**Vehicles (20)**" in text and "* …and 12 more" in text and text.count("\n* **AA-") == 8

    refused = answer_offline("Show the dashboard summary", _Runner(status="halted", halt="insights is not permitted for role driver"), "tok")
    assert refused.startswith("**Couldn't fetch the dashboard summary.** insights is not permitted for role driver")


# --- OrchestratorSession: all models down -> offline answer, otherwise the original error ----


from orchestrator.graph import OrchestratorDeps  # noqa: E402
from orchestrator.session import OrchestratorSession  # noqa: E402


def _token():
    payload = {"sub": "u1", "org": "org-1", "role": "admin", "exp": datetime.now(timezone.utc) + timedelta(minutes=30)}
    return jwt.encode(payload, "irrelevant-signing-key", algorithm="HS256")


class _DeadLLM:
    def __init__(self, error):
        self.error = error

    def bind_tools(self, tools):
        return self

    def invoke(self, messages, **kw):
        raise self.error


def test_when_every_model_is_down_a_plain_read_is_still_answered() -> None:
    runner = _Runner({"overdue": [], "upcoming": []})
    session = OrchestratorSession(_token(), deps=OrchestratorDeps(llm=_DeadLLM(_err(openai.RateLimitError, 429)), runner=runner))

    result = session.run("Which vehicles are due for service?")

    assert result.status == "done"
    assert result.final_response.endswith(FOOTNOTE) and "**Overdue service" in result.final_response
    assert session.state["chat_history"][-1]["content"] == result.final_response  # it joins the conversation


@pytest.mark.parametrize(
    "error",
    [_err(openai.RateLimitError, 429), openai.APITimeoutError(request=httpx.Request("POST", "https://x")), InvalidModelOutput("bad")],
)
def test_a_write_request_is_never_guessed_at_when_the_models_are_down(error) -> None:
    session = OrchestratorSession(_token(), deps=OrchestratorDeps(llm=_DeadLLM(error), runner=_Runner()))
    with pytest.raises(type(error)):
        session.run("Log a trip for vehicle ABC-123 from 45000 to 45250 km")


def test_a_real_bug_is_not_mistaken_for_a_model_outage() -> None:
    session = OrchestratorSession(_token(), deps=OrchestratorDeps(llm=_DeadLLM(ValueError("our bug")), runner=_Runner()))
    with pytest.raises(ValueError):
        session.run("Which vehicles are due for service?")


# --- token budget ---------------------------------------------------------------------------


def test_system_prompt_stays_under_350_tokens_and_planner_and_reply_are_capped() -> None:
    import tiktoken

    from orchestrator import graph

    tokens = len(tiktoken.get_encoding("cl100k_base").encode(graph._SYSTEM_PROMPT))
    assert tokens < 350, tokens
    assert graph.PLANNER_MAX_TOKENS == 350 and graph.SYNTHESIS_MAX_TOKENS == 500


def test_only_the_last_six_messages_reach_the_model() -> None:
    from orchestrator.graph import HISTORY_WINDOW, _history_to_messages

    history = [{"role": "user" if i % 2 == 0 else "assistant", "content": f"message {i}"} for i in range(20)]
    messages = _history_to_messages({"chat_history": history, "scratchpad": []})
    texts = [str(m.content) for m in messages[1:]]  # [0] is the system prompt
    assert HISTORY_WINDOW == 6 and texts == [f"message {i}" for i in range(14, 20)]


# --- shared chain and /health ---------------------------------------------------------------


def test_every_session_shares_one_model_chain_so_cooldowns_are_remembered(monkeypatch) -> None:
    from orchestrator import graph

    monkeypatch.setenv("GROQ_API_KEY", "gsk-test")
    monkeypatch.delenv("OPEN_ROUTER_API_KEY", raising=False)
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    graph.get_shared_llm.cache_clear()
    try:
        assert graph._default_llm() is graph._default_llm()
    finally:
        graph.get_shared_llm.cache_clear()


def test_health_reports_model_status_spend_and_token_usage(monkeypatch) -> None:
    from fastapi.testclient import TestClient

    import server

    llm = FailoverChatModel(_Model("groq", error=_err(openai.RateLimitError, 429, headers={"retry-after": "600"})), _Model("router"))
    llm.invoke("hi")
    monkeypatch.setattr(server, "get_shared_llm", lambda: llm)

    body = TestClient(server.app).get("/health").json()

    assert body["status"] == "ok"
    assert [(m["model"], m["state"]) for m in body["llm_models"]] == [("groq", "cooling_down"), ("router", "ready")]
    assert body["llm_usage"]["budget_usd"] == 5 and body["llm_usage"]["paid_calls_enabled"] is True
    assert (body["llm_usage"]["calls"], body["llm_usage"]["tokens_in"], body["llm_usage"]["tokens_out"]) == (1, 100, 10)


def test_compact_tool_schemas_keep_the_contract_and_stay_within_the_token_budget() -> None:
    import json

    import tiktoken
    from langchain_core.utils.function_calling import convert_to_openai_tool

    from orchestrator.tools import build_llm_tools

    tools = {t.name: convert_to_openai_tool(t)["function"] for t in build_llm_tools(include_memory=True, include_documents=True)}
    encoded = json.dumps(tools)
    assert '"title"' not in encoded and '"anyOf": [{"type": "string"}, {"type": "null"}]' not in encoded

    trip = tools["fuel"]["parameters"]["properties"]["trip_fields"]
    assert set(trip["required"]) == {"driver_id", "vehicle_id", "start_time", "end_time", "start_odometer", "end_odometer"}
    assert "LITERS" in trip["properties"]["fuel_consumed"]["description"]  # the guidance the model needs survives
    assert trip["additionalProperties"] is False  # strictness survives too
    assert tools["search_documents"]["parameters"]["required"] == ["query"]

    tokens = len(tiktoken.get_encoding("cl100k_base").encode(encoded))
    assert tokens < 3300, tokens  # was 3,911 before compaction


def test_with_the_llm_down_the_fuel_question_is_answered_as_a_calculated_markdown_summary() -> None:
    """The bug report's scenario end to end: offline LLM, fuel question, real session. The user
    gets a clean computed summary, never a `fuel logs (3): vehicle_plate=...` dump."""
    session = OrchestratorSession(_token(), deps=OrchestratorDeps(llm=_DeadLLM(openai.APITimeoutError(request=httpx.Request("POST", "https://x"))), runner=_Runner(FUEL_SUMMARY)))

    result = session.run(FUEL_QUESTION)

    assert result.status == "done"
    assert result.final_response.startswith("**Fuel & Cost Summary for Vehicle AB-1234 (Past Month)**\n* **Total Fuel Consumed:** 155 Liters")
    assert "* **Average Cost per km:** Rs 43.50 / km" in result.final_response
    assert "vehicle_plate=" not in result.final_response and "fuel logs (" not in result.final_response
