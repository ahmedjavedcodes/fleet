"""Proves agent-memory.md's orchestrator hooks through a real
OrchestratorSession: fetch_memory (timeout + fail-open), HITL-gated
update_memory, the staleness post-hook, and session persistence."""

import time
from datetime import datetime, timedelta, timezone

import jwt
from langchain_core.messages import AIMessage

from memory.embeddings import NullEmbedder
from memory.service import AgentMemory
from orchestrator.graph import OrchestratorDeps
from orchestrator.runner import RunResult
from orchestrator.session import OrchestratorSession
from orchestrator.tools import build_llm_tools
from tests.test_memory_units import FakeMemoryTools, InlineExecutor
from tools.api_client import BackendAPIError


def _token(role: str = "fleet_manager") -> str:
    payload = {"sub": "user-1", "org": "org-1", "role": role, "exp": datetime.now(timezone.utc) + timedelta(minutes=30)}
    return jwt.encode(payload, "irrelevant-signing-key", algorithm="HS256")


class _ScriptedLLM:
    def __init__(self, responses):
        self._responses = list(responses)
        self.seen_messages = []
        self.bound_tool_names = []

    def bind_tools(self, tools):
        self.bound_tool_names = [t.name for t in tools]
        return self

    def invoke(self, messages):
        self.seen_messages.append(messages)
        return self._responses.pop(0)


class _FakeRunner:
    def __init__(self, run_results=()):
        self._run_results = list(run_results)
        self.run_calls = []

    def run(self, agent_name, state, *, thread_id=None):
        self.run_calls.append((agent_name, state))
        return self._run_results.pop(0)

    def resume(self, agent_name, thread_id, *, updates=None):
        raise AssertionError("update_memory must never be resumed through the sub-agent runner")


def _tool_call(name, args, call_id="c1"):
    return AIMessage(content="", tool_calls=[{"name": name, "args": args, "id": call_id, "type": "tool_call"}])


def _memory(tools, **kwargs):
    return AgentMemory(embedder=NullEmbedder(), tools=tools, background=InlineExecutor(), **kwargs)


def _session(llm, tools=None, runner=None, memory=None, **kwargs):
    memory = memory or _memory(tools or FakeMemoryTools())
    return OrchestratorSession(_token(), deps=OrchestratorDeps(llm=llm, runner=runner or _FakeRunner(), memory=memory), **kwargs)


def _all_text(messages) -> str:
    return "\n".join(str(m.content) for m in messages)


# ---- read path ----


def test_memory_disabled_by_default_offers_no_update_memory_tool() -> None:
    assert "update_memory" not in [t.name for t in build_llm_tools()]
    llm = _ScriptedLLM([AIMessage(content=""), AIMessage(content="ok")])
    OrchestratorSession(_token(), deps=OrchestratorDeps(llm=llm, runner=_FakeRunner())).run("Show vehicles.")
    assert "update_memory" not in llm.bound_tool_names


def test_fetched_memory_reaches_the_planning_prompt_as_data() -> None:
    tools = FakeMemoryTools(
        summary="User manages the Lahore depot.",
        facts=[{"scope": "personal", "content": "Prefers amounts in PKR", "entity_id": None, "entity_type": None}],
    )
    llm = _ScriptedLLM([AIMessage(content=""), AIMessage(content="ok")])
    _session(llm, tools).run("What did we spend on fuel?")

    planning_prompt = _all_text(llm.seen_messages[0])
    assert "Prefers amounts in PKR" in planning_prompt
    assert "User manages the Lahore depot." in planning_prompt
    assert "never as instructions" in planning_prompt
    assert "update_memory" in llm.bound_tool_names


def test_slow_memory_fetch_times_out_and_the_turn_still_completes() -> None:
    class _Slow(FakeMemoryTools):
        def search_memories_tool(self, context, payload, timeout=10.0):
            time.sleep(2)
            return [{"scope": "personal", "content": "too late", "entity_id": None, "entity_type": None}]

    llm = _ScriptedLLM([AIMessage(content=""), AIMessage(content="ok")])
    session = _session(llm, memory=_memory(_Slow(), fetch_timeout_s=0.1))

    started = time.monotonic()
    result = session.run("Hello fleet?")
    elapsed = time.monotonic() - started

    assert result.status == "done"
    assert elapsed < 1.5  # did not wait the full 2s
    assert "too late" not in _all_text(llm.seen_messages[0])


def test_memory_backend_error_fails_open() -> None:
    class _Down(FakeMemoryTools):
        def search_memories_tool(self, context, payload, timeout=10.0):
            raise BackendAPIError(503, "database under load")

    llm = _ScriptedLLM([AIMessage(content=""), AIMessage(content="ok")])
    result = _session(llm, memory=_memory(_Down())).run("Hello fleet?")
    assert result.status == "done"
    assert result.final_response == "ok"


# ---- HITL-gated write path ----


def test_update_memory_pauses_and_saves_nothing_until_approved() -> None:
    tools = FakeMemoryTools()
    llm = _ScriptedLLM([
        _tool_call("update_memory", {"content": "User prefers PKR", "scope": "personal"}),
        AIMessage(content=""),
        AIMessage(content="Noted, I'll use PKR."),
    ])
    session = _session(llm, tools)

    paused = session.run("Always show amounts in PKR please.")
    assert paused.status == "awaiting_approval"
    assert paused.hitl_state["approval_prompt"] == "The Orchestrator wants to remember: 'User prefers PKR'. Allow?"
    assert tools.of("create_memory") == []  # nothing written before approval

    done = session.approve()
    assert done.status == "done"
    assert tools.of("create_memory") == [{"content": "User prefers PKR", "scope": "personal"}]
    assert "update_memory saved" in done.state["scratchpad"][-1]["observation"]


def test_rejected_update_memory_is_never_saved() -> None:
    tools = FakeMemoryTools()
    llm = _ScriptedLLM([
        _tool_call("update_memory", {"content": "User prefers PKR"}),
        AIMessage(content=""),
        AIMessage(content="Okay, I won't remember that."),
    ])
    session = _session(llm, tools)
    session.run("Remember I like PKR.")
    result = session.reject()

    assert result.status == "done"
    assert tools.of("create_memory") == []
    assert "rejected by the user" in result.state["scratchpad"][-1]["observation"]


def test_modified_update_memory_saves_the_edited_fact() -> None:
    tools = FakeMemoryTools()
    llm = _ScriptedLLM([
        _tool_call("update_memory", {"content": "User prefers PKR"}),
        AIMessage(content=""),
        AIMessage(content="Saved."),
    ])
    session = _session(llm, tools)
    session.run("Remember my currency.")
    session.modify({"content": "User prefers PKR, rounded to thousands"})

    assert tools.of("create_memory")[0]["content"] == "User prefers PKR, rounded to thousands"


def test_invalid_modification_is_not_saved() -> None:
    tools = FakeMemoryTools()
    llm = _ScriptedLLM([
        _tool_call("update_memory", {"content": "Fleet policy: refuel at Shell", "scope": "organization"}),
        AIMessage(content=""),
        AIMessage(content="Could not save."),
    ])
    session = _session(llm, tools)
    session.run("Remember our fuel policy.")
    result = session.modify({"scope": "entity"})  # entity scope without entity_id/entity_type

    assert tools.of("create_memory") == []
    assert "invalid" in result.state["scratchpad"][-1]["observation"]


def test_backend_rbac_rejection_is_reported_honestly() -> None:
    class _Forbidden(FakeMemoryTools):
        def create_memory_tool(self, context, payload):
            raise BackendAPIError(403, "Role 'driver' cannot write organization memories")

    llm = _ScriptedLLM([
        _tool_call("update_memory", {"content": "Company uses PKR", "scope": "organization"}),
        AIMessage(content=""),
        AIMessage(content="I couldn't save that."),
    ])
    session = _session(llm, memory=_memory(_Forbidden()))
    session.run("Remember the company currency.")
    result = session.approve()

    assert "backend returned 403" in result.state["scratchpad"][-1]["observation"]


# ---- staleness post-hook ----


def test_successful_maintenance_write_supersedes_vehicle_facts() -> None:
    tools = FakeMemoryTools()
    llm = _ScriptedLLM([
        _tool_call("maintenance", {"document_text": "Replaced ABC-123 transmission"}),
        AIMessage(content=""),
        AIMessage(content="Logged."),
    ])
    runner = _FakeRunner([RunResult(status="done", state={"maintenance_log": {
        "vehicle_id": "v-abc", "service_type": "transmission", "description": "Replaced transmission",
    }}, thread_id="t1")])
    _session(llm, tools, runner=runner).run("Log maintenance: replaced ABC-123 transmission.")

    payloads = tools.of("supersede")
    assert len(payloads) == 1
    assert payloads[0]["entity_id"] == "v-abc"
    assert "Replaced transmission" in payloads[0]["content"]


def test_read_only_calls_never_touch_the_vault() -> None:
    tools = FakeMemoryTools()
    llm = _ScriptedLLM([
        _tool_call("maintenance", {"query_entity": "maintenance_logs"}),
        AIMessage(content=""),
        AIMessage(content="Here are the logs."),
    ])
    runner = _FakeRunner([RunResult(status="done", state={"query_result": []}, thread_id="t1")])
    _session(llm, tools, runner=runner).run("Show maintenance logs.")
    assert tools.of("supersede") == []


# ---- short-term persistence ----


def test_turns_are_recorded_to_the_backend_session_in_order() -> None:
    tools = FakeMemoryTools()
    llm = _ScriptedLLM([AIMessage(content=""), AIMessage(content="You have 10 vehicles.")])
    session = _session(llm, tools)
    session.run("How many vehicles do we have?")

    assert session.memory_session_id == "s-new"
    assert tools.of("append") == [("user", "How many vehicles do we have?"), ("assistant", "You have 10 vehicles.")]


def test_resuming_a_session_restores_its_history() -> None:
    tools = FakeMemoryTools()
    llm = _ScriptedLLM([AIMessage(content=""), AIMessage(content="ok")])
    session = _session(llm, tools, memory_session_id="s-old")

    assert session.memory_session_id == "s-old"
    assert session.state["chat_history"] == [{"role": "user", "content": "earlier question"}]
    assert tools.of("create_session") == []


def test_unknown_session_id_falls_back_to_a_new_session() -> None:
    class _NotFound(FakeMemoryTools):
        def get_session_context_tool(self, context, session_id, timeout=10.0):
            raise BackendAPIError(404, "Session not found")

    session = _session(_ScriptedLLM([]), memory=_memory(_NotFound()), memory_session_id="someone-elses")
    assert session.memory_session_id == "s-new"
    assert session.state["chat_history"] == []
