"""The deterministic `fuel_summary` query: pure maths, the paginated fetch, the agent branch, and
the schema the LLM sees.

The maths lives in agents/fuel/summary.py and is shared with the offline fallback, so the LLM is
never asked to add up rows itself. The fake backend below honours the real /api/v1/fuel contract
(oldest first, vehicle_id / date_from filters, skip / limit) so the pagination is exercised for real.
"""

from datetime import date, datetime, timedelta, timezone

import jwt
import pytest

from agents.fuel.graph import FuelAgentDeps, get_compiled_fuel_graph
from agents.fuel.summary import render_fuel_summary, summarize_fuel
from mcp_server import foundation_tools as vft
from mcp_server import fuel_tools as ft
from tools.auth_context import AgentContext, build_context

TODAY = date(2026, 9, 30)


def _token(role: str = "fleet_manager") -> str:
    payload = {"sub": "user-1", "org": "org-1", "role": role, "exp": datetime.now(timezone.utc) + timedelta(minutes=30)}
    return jwt.encode(payload, "irrelevant-signing-key", algorithm="HS256")


def _fill(plate: str, day: str, litres: float, cost: float, odometer: float, vehicle_id: str | None = None) -> dict:
    return {
        "vehicle_id": vehicle_id or {"AB-1234": "v1", "CD-5678": "v2"}[plate],
        "vehicle_plate": plate,
        "date": day,
        "liters_filled": str(litres),
        "total_cost": str(cost),
        "odometer_reading": odometer,
    }


RECENT = [
    _fill("AB-1234", "2026-09-05", 60, 16800, 45000),
    _fill("AB-1234", "2026-09-14", 50, 14000, 45500),
    _fill("AB-1234", "2026-09-27", 45, 12700, 46000),
]
OTHER_VEHICLE = _fill("CD-5678", "2026-09-20", 10, 2800, 1000)


# --- the pure maths ----------------------------------------------------------------------------


def test_one_vehicle_gets_litres_cost_distance_and_cost_per_km_in_the_requested_layout() -> None:
    summary = summarize_fuel([*RECENT, OTHER_VEHICLE], plate="ab-1234", days=30, today=TODAY)

    assert (summary["liters"], summary["total_cost"], summary["distance_km"], summary["cost_per_km"]) == (155.0, 43500.0, 1000.0, 43.5)
    assert summary["answer_markdown"] == (
        "**Fuel & Cost Summary for Vehicle AB-1234 (Past Month)**\n"
        "* **Total Fuel Consumed:** 155 Liters\n"
        "* **Total Fuel Cost:** Rs 43,500\n"
        "* **Total Distance Covered:** 1,000 km (45,000 km → 46,000 km)\n"
        "* **Average Cost per km:** Rs 43.50 / km"
    )


def test_the_fleet_total_sums_each_vehicles_own_odometer_span_and_ignores_single_fill_vehicles_for_cost_per_km() -> None:
    summary = summarize_fuel([*RECENT, OTHER_VEHICLE, _fill("CD-5678", "2026-09-25", 20, 5600, 1400)], days=30, today=TODAY)

    assert summary["vehicles"] == 2 and summary["fills"] == 5
    assert summary["liters"] == 185.0 and summary["total_cost"] == 51900.0
    assert summary["distance_km"] == 1400.0  # 1000 (AB-1234) + 400 (CD-5678), never a fleet-wide max-min
    assert summary["cost_per_km"] == pytest.approx(51900 / 1400, abs=0.01)
    assert summary["start_odometer"] is None  # a range only makes sense for one vehicle
    assert summary["answer_markdown"].startswith("**Fuel & Cost Summary for the Fleet (Past Month)**")
    assert "1,400 km\n" in summary["answer_markdown"]


def test_money_is_summed_exactly_not_as_floats() -> None:
    rows = [_fill("AB-1234", "2026-09-01", 0.1, 0.1, 100), _fill("AB-1234", "2026-09-02", 0.2, 0.2, 200)]
    summary = summarize_fuel(rows, today=TODAY)
    assert (summary["liters"], summary["total_cost"]) == (0.3, 0.3)  # float addition would give 0.30000000000000004


def test_the_window_excludes_older_fills_and_the_label_follows_the_period() -> None:
    old = _fill("AB-1234", "2026-07-01", 50, 14000, 30000)
    assert summarize_fuel([old, *RECENT], days=30, today=TODAY)["fills"] == 3
    assert summarize_fuel([old, *RECENT], today=TODAY)["fills"] == 4  # no window = all time
    titles = {days: render_fuel_summary(summarize_fuel(RECENT, days=days, today=TODAY)).splitlines()[0] for days in (7, 30, 90, None)}
    assert titles == {
        7: "**Fuel & Cost Summary for the Fleet (Past Week)**",
        30: "**Fuel & Cost Summary for the Fleet (Past Month)**",
        90: "**Fuel & Cost Summary for the Fleet (Past 90 Days)**",
        None: "**Fuel & Cost Summary for the Fleet**",
    }


def test_it_is_honest_when_distance_cannot_be_computed_or_there_is_no_data() -> None:
    one = summarize_fuel([RECENT[0]], plate="AB-1234", today=TODAY)
    assert one["distance_km"] is None and one["cost_per_km"] is None
    assert "not available (needs at least two fills)" in one["answer_markdown"]
    assert "Average Cost per km:** not available" in one["answer_markdown"]

    none = summarize_fuel([], plate="CD-5678", days=30, today=TODAY)
    assert none["fills"] == 0 and "No fuel logs recorded for this period." in none["answer_markdown"]
    assert "Rs 0" not in none["answer_markdown"]


def test_unparseable_numbers_are_skipped_rather_than_crashing_the_summary() -> None:
    rows = [_fill("AB-1234", "2026-09-01", 10, 2800, 100), {**_fill("AB-1234", "2026-09-02", 5, 1400, 200), "liters_filled": None, "total_cost": "n/a"}]
    summary = summarize_fuel(rows, today=TODAY)
    assert (summary["liters"], summary["total_cost"], summary["distance_km"]) == (10.0, 2800.0, 100.0)


# --- a backend that behaves like the real /api/v1/fuel -----------------------------------------


class _FuelBackend:
    def __init__(self, fuel: list[dict]) -> None:
        self.fuel = fuel
        self.vehicles = [{"id": "v1", "plate_number": "AB-1234"}, {"id": "v2", "plate_number": "CD-5678"}]
        self.fuel_params: list[dict] = []

    def __call__(self, method, path, *, token=None, json=None, params=None, timeout=10.0):
        if path == "/api/v1/vehicles":
            return list(self.vehicles)
        assert (method, path) == ("GET", "/api/v1/fuel"), (method, path)
        params = params or {}
        self.fuel_params.append(dict(params))
        rows = sorted(self.fuel, key=lambda r: r["date"])  # oldest first, like the real endpoint
        if "vehicle_id" in params:
            rows = [r for r in rows if r["vehicle_id"] == params["vehicle_id"]]
        if "date_from" in params:
            rows = [r for r in rows if r["date"] >= params["date_from"]]
        skip, limit = params.get("skip", 0), params.get("limit", 100)  # the real default page is 100
        return rows[skip : skip + limit]


def _history(extra: list[dict]) -> list[dict]:
    """120 old fills for AB-1234 (more than one default page) followed by `extra`."""
    start = date(2025, 1, 1)
    old = [_fill("AB-1234", (start + timedelta(days=i)).isoformat(), 40, 11000, 10000 + 400 * i) for i in range(120)]
    return [*old, *extra]


@pytest.fixture
def backend(monkeypatch: pytest.MonkeyPatch):
    fake = _FuelBackend(_history([*RECENT, OTHER_VEHICLE]))
    monkeypatch.setattr(ft, "call_backend", fake)
    monkeypatch.setattr(vft, "call_backend", fake)
    return fake


def _graph():
    return get_compiled_fuel_graph(FuelAgentDeps(today=lambda: TODAY))


def _context() -> AgentContext:
    return build_context(_token())


# --- the paginated fetch -----------------------------------------------------------------------


def test_the_window_fetch_filters_on_the_server_and_follows_every_page(backend: _FuelBackend) -> None:
    backend.fuel = _history([])
    backend.fuel += [_fill("AB-1234", "2026-09-01", 1, 1, 1) for _ in range(1000)]  # 1,120 rows -> three pages

    rows, complete = ft.get_fuel_logs_window_tool(_context())

    assert (len(rows), complete) == (1120, True)
    assert [(p["skip"], p["limit"]) for p in backend.fuel_params] == [(0, 500), (500, 500), (1000, 500)]

    backend.fuel_params.clear()
    rows, _ = ft.get_fuel_logs_window_tool(_context(), vehicle_id="v1", date_from="2026-09-01")
    assert len(rows) == 1000
    assert all(p["vehicle_id"] == "v1" and p["date_from"] == "2026-09-01" for p in backend.fuel_params)


def test_a_full_last_page_is_followed_by_one_more_request_and_a_runaway_fetch_is_reported_incomplete(backend: _FuelBackend, monkeypatch) -> None:
    backend.fuel = [_fill("AB-1234", "2026-09-01", 1, 1, 1) for _ in range(1000)]
    rows, complete = ft.get_fuel_logs_window_tool(_context())
    assert (len(rows), complete, len(backend.fuel_params)) == (1000, True, 3)  # 500, 500, then an empty page

    monkeypatch.setattr(ft, "MAX_FUEL_PAGES", 1)
    rows, complete = ft.get_fuel_logs_window_tool(_context())
    assert (len(rows), complete) == (500, False)


# --- the agent branch --------------------------------------------------------------------------


def test_the_agent_summarises_recent_fills_even_when_older_history_exceeds_the_default_page(backend: _FuelBackend) -> None:
    """Regression: the plain fuel_logs read is oldest-first and capped at 100 rows, so a naive sum
    would have missed every fill from the past month."""
    state = _graph().invoke({"token": _token(), "query_entity": "fuel_summary", "query_plate": "ab 1234", "query_days": 30})

    assert state["stage"] == "done"
    result = state["query_result"]
    assert (result["fills"], result["liters"], result["total_cost"], result["cost_per_km"], result["complete"]) == (3, 155.0, 43500.0, 43.5, True)
    assert result["answer_markdown"].startswith("**Fuel & Cost Summary for Vehicle AB-1234 (Past Month)**")
    assert backend.fuel_params[0]["vehicle_id"] == "v1" and backend.fuel_params[0]["date_from"] == "2026-08-31"


def test_the_agent_summarises_the_whole_fleet_when_no_plate_is_given(backend: _FuelBackend) -> None:
    result = _graph().invoke({"token": _token(), "query_entity": "fuel_summary", "query_days": 30})["query_result"]

    assert (result["vehicles"], result["fills"], result["liters"], result["total_cost"]) == (2, 4, 165.0, 46300.0)
    assert result["answer_markdown"].startswith("**Fuel & Cost Summary for the Fleet (Past Month)**")
    assert "vehicle_id" not in backend.fuel_params[0]


def test_an_unknown_plate_halts_with_a_reason_instead_of_summarising_nothing(backend: _FuelBackend) -> None:
    state = _graph().invoke({"token": _token(), "query_entity": "fuel_summary", "query_plate": "ZZ-9999"})

    assert state["stage"] == "halted" and "ZZ-9999" in state["halt_reason"]
    assert backend.fuel_params == []  # never fetched fuel rows for a vehicle that does not exist


def test_a_truncated_fetch_is_flagged_in_the_summary(backend: _FuelBackend, monkeypatch) -> None:
    monkeypatch.setattr(ft, "FUEL_PAGE_SIZE", 50)
    monkeypatch.setattr(ft, "MAX_FUEL_PAGES", 1)

    result = _graph().invoke({"token": _token(), "query_entity": "fuel_summary"})["query_result"]

    assert result["complete"] is False and "first 10,000 fuel logs only" in result["answer_markdown"]


# --- what the LLM sees -------------------------------------------------------------------------


def test_the_fuel_tool_schema_tells_the_model_to_use_fuel_summary_instead_of_adding_up_logs() -> None:
    from langchain_core.utils.function_calling import convert_to_openai_tool

    from orchestrator.tools import build_llm_tools

    fuel = next(convert_to_openai_tool(t)["function"] for t in build_llm_tools(include_memory=False, include_documents=False) if t.name == "fuel")

    assert (
        "Use this tool to calculate total fuel consumed, total cost, and average cost per kilometer. "
        "Do NOT manually add up individual fuel logs."
    ) in fuel["description"]
    props = fuel["parameters"]["properties"]
    assert "fuel_summary" in props["query_entity"]["enum"]
    assert {"query_plate", "query_days"} <= set(props)
    assert fuel["parameters"]["additionalProperties"] is False


def test_query_plate_is_normalised_like_every_other_plate_the_model_passes() -> None:
    from orchestrator.normalization import normalize_tool_args

    args = normalize_tool_args("fuel", {"query_entity": "fuel_summary", "query_plate": " ab-1234 ", "query_days": 30})
    assert args["query_plate"] == "AB-1234"


@pytest.mark.parametrize("bad", [{"query_days": 0}, {"query_days": 400}, {"query_plate": "x" * 21}, {"query_entity": "everything"}])
def test_bad_summary_arguments_are_rejected_by_the_strict_schema(bad) -> None:
    from pydantic import ValidationError

    from orchestrator.tool_schemas import FuelToolInput

    with pytest.raises(ValidationError):
        FuelToolInput(**bad)
