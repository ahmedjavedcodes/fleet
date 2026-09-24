"""Unit tests for ai_agents/memory: embedders, staleness extraction, the
background summarizer, and AgentMemory -- no network, no backend."""

from concurrent.futures import Executor, Future

import httpx
import pytest

from memory import embeddings
from memory.embeddings import EMBEDDING_DIM, EmbeddingError, NomicAPIEmbedder, NullEmbedder, OllamaEmbedder, get_default_embedder
from memory.service import AgentMemory
from memory.staleness import extract_entity_facts
from memory.summarizer import SessionSummarizer, estimate_tokens
from tools.api_client import BackendAPIError
from tools.auth_context import AgentContext

CTX = AgentContext(token="t", user_id="u1", organization_id="org-1", role="fleet_manager")


class InlineExecutor(Executor):
    def submit(self, fn, *args, **kwargs):
        future: Future = Future()
        try:
            future.set_result(fn(*args, **kwargs))
        except Exception as exc:  # noqa: BLE001
            future.set_exception(exc)
        return future


class _Response:
    def __init__(self, payload):
        self._payload = payload

    def raise_for_status(self):
        pass

    def json(self):
        return self._payload


# ---- embeddings ----


def test_null_embedder_returns_none() -> None:
    assert NullEmbedder().embed("anything", task="search_query") is None


def test_ollama_embedder_adds_nomic_task_prefix(monkeypatch) -> None:
    sent = {}

    def _post(url, json, timeout):
        sent.update(url=url, json=json)
        return _Response({"embeddings": [[0.1] * EMBEDDING_DIM]})

    monkeypatch.setattr(embeddings.httpx, "post", _post)
    vector = OllamaEmbedder(base_url="http://ollama:11434/").embed("oil leak", task="search_document")

    assert len(vector) == EMBEDDING_DIM
    assert sent["url"] == "http://ollama:11434/api/embed"
    assert sent["json"]["input"] == "search_document: oil leak"


def test_nomic_api_embedder_sends_task_type(monkeypatch) -> None:
    sent = {}

    def _post(url, headers, json, timeout):
        sent.update(headers=headers, json=json)
        return _Response({"embeddings": [[0.2] * EMBEDDING_DIM]})

    monkeypatch.setattr(embeddings.httpx, "post", _post)
    NomicAPIEmbedder(api_key="k").embed("oil leak", task="search_query")

    assert sent["json"]["task_type"] == "search_query"
    assert sent["json"]["dimensionality"] == EMBEDDING_DIM
    assert sent["headers"]["Authorization"] == "Bearer k"


def test_wrong_dimension_is_rejected(monkeypatch) -> None:
    monkeypatch.setattr(embeddings.httpx, "post", lambda url, json, timeout: _Response({"embeddings": [[0.1] * 384]}))
    with pytest.raises(EmbeddingError):
        OllamaEmbedder().embed("x", task="search_query")


def test_default_embedder_is_null(monkeypatch) -> None:
    monkeypatch.delenv("MEMORY_EMBEDDER", raising=False)
    assert isinstance(get_default_embedder(), NullEmbedder)


def test_nomic_embedder_requires_key(monkeypatch) -> None:
    monkeypatch.setenv("MEMORY_EMBEDDER", "nomic")
    monkeypatch.delenv("NOMIC_API_KEY", raising=False)
    with pytest.raises(EmbeddingError):
        get_default_embedder()


def test_unknown_embedder_is_rejected(monkeypatch) -> None:
    monkeypatch.setenv("MEMORY_EMBEDDER", "openai")
    with pytest.raises(EmbeddingError):
        get_default_embedder()


# ---- staleness extraction ----


def test_maintenance_write_becomes_vehicle_fact() -> None:
    facts = extract_entity_facts("maintenance", {"maintenance_log": {
        "vehicle_id": "v1", "service_type": "transmission", "description": "Replaced gearbox",
        "date": "2026-09-01", "odometer_at_service": 120000,
    }})
    assert len(facts) == 1
    assert facts[0].entity_type == "vehicle" and facts[0].entity_id == "v1"
    assert "Replaced gearbox" in facts[0].content and "120000 km" in facts[0].content


def test_incident_with_driver_produces_vehicle_and_driver_facts() -> None:
    facts = extract_entity_facts("accountability", {"created_record": {
        "vehicle_id": "v1", "driver_id": "d1", "severity": "severe", "incident_type": "damage",
        "date": "2026-09-02", "description": "Rear-ended at depot",
    }})
    assert {(f.entity_type, f.entity_id) for f in facts} == {("vehicle", "v1"), ("driver", "d1")}


def test_assignment_and_release_facts() -> None:
    assigned = extract_entity_facts("assignment", {"created_record": {"vehicle_id": "v1", "driver_id": "d1", "assigned_at": "t0"}})
    released = extract_entity_facts("assignment", {"created_record": {"vehicle_id": "v1", "driver_id": "d1", "released_at": "t1"}})
    assert "currently assigned to driver d1" in assigned[0].content
    assert "released by driver d1" in released[0].content


def test_agents_without_entity_state_produce_no_facts() -> None:
    assert extract_entity_facts("fuel", {"created_record": {"vehicle_id": "v1"}}) == []
    assert extract_entity_facts("maintenance", {"updated_parts": []}) == []


# ---- summarizer ----


class _FakeSummaryLLM:
    def __init__(self, replies):
        self.replies = list(replies)
        self.calls = []

    def invoke(self, messages):
        self.calls.append(messages)

        class _R:
            content = self.replies.pop(0)

        return _R()


def _snapshot(n_messages, *, summary="", version=0):
    return {
        "session": {"running_summary": summary, "summary_version": version},
        "unsummarized_messages": [{"id": f"m{i}", "role": "user", "content": f"message {i}"} for i in range(n_messages)],
    }


def test_summarizer_folds_all_but_the_window() -> None:
    applied = {}
    llm = _FakeSummaryLLM(["User discussed messages 0 and 1."])
    summarizer = SessionSummarizer(
        llm=llm, window_size=4,
        get_context=lambda ctx, sid: _snapshot(6, version=3),
        apply_summary=lambda ctx, sid, **kw: applied.update(kw),
    )

    assert summarizer.summarize(CTX, "s1") is True
    assert applied["message_ids"] == ["m0", "m1"]
    assert applied["expected_summary_version"] == 3
    assert applied["running_summary"] == "User discussed messages 0 and 1."


def test_summarizer_skips_llm_when_nothing_to_fold() -> None:
    llm = _FakeSummaryLLM([])
    summarizer = SessionSummarizer(llm=llm, get_context=lambda ctx, sid: _snapshot(4), apply_summary=lambda *a, **k: None)
    assert summarizer.summarize(CTX, "s1") is False
    assert llm.calls == []


def test_summarizer_recompresses_an_oversized_summary() -> None:
    applied = {}
    llm = _FakeSummaryLLM(["x" * 8000, "short summary"])
    summarizer = SessionSummarizer(
        llm=llm, max_summary_tokens=1000,
        get_context=lambda ctx, sid: _snapshot(6),
        apply_summary=lambda ctx, sid, **kw: applied.update(kw),
    )
    summarizer.summarize(CTX, "s1")
    assert len(llm.calls) == 2
    assert applied["running_summary"] == "short summary"


def test_summarizer_hard_caps_when_recompression_keeps_failing() -> None:
    applied = {}
    llm = _FakeSummaryLLM(["x" * 8000] * 3)
    summarizer = SessionSummarizer(
        llm=llm, max_summary_tokens=1000,
        get_context=lambda ctx, sid: _snapshot(6),
        apply_summary=lambda ctx, sid, **kw: applied.update(kw),
    )
    summarizer.summarize(CTX, "s1")
    assert estimate_tokens(applied["running_summary"]) <= 1000


def test_summarizer_losing_a_race_returns_false_quietly() -> None:
    def _conflict(*args, **kwargs):
        raise BackendAPIError(409, "Summary was updated concurrently")

    summarizer = SessionSummarizer(llm=_FakeSummaryLLM(["s"]), get_context=lambda ctx, sid: _snapshot(6), apply_summary=_conflict)
    assert summarizer.summarize(CTX, "s1") is False


def test_summarizer_never_raises_on_llm_failure() -> None:
    class _Broken:
        def invoke(self, messages):
            raise RuntimeError("Groq down")

    summarizer = SessionSummarizer(llm=_Broken(), get_context=lambda ctx, sid: _snapshot(6), apply_summary=lambda *a, **k: None)
    assert summarizer.summarize(CTX, "s1") is False


# ---- AgentMemory ----


class FakeMemoryTools:
    def __init__(self, *, facts=None, summary="", needs_summarization=False, supersede_error=None):
        self.facts = facts or []
        self.summary = summary
        self.needs_summarization = needs_summarization
        self.supersede_error = supersede_error
        self.calls: list[tuple[str, object]] = []

    def create_session_tool(self, context, timeout=10.0):
        self.calls.append(("create_session", None))
        return {"id": "s-new"}

    def get_session_context_tool(self, context, session_id, timeout=10.0):
        self.calls.append(("get_context", session_id))
        return {
            "session": {"running_summary": self.summary, "summary_version": 0},
            "unsummarized_messages": [{"id": "m1", "role": "user", "content": "earlier question"}],
        }

    def append_message_tool(self, context, session_id, role, content):
        self.calls.append(("append", (role, content)))
        return {"needs_summarization": self.needs_summarization}

    def search_memories_tool(self, context, payload, timeout=10.0):
        self.calls.append(("search", payload))
        return self.facts

    def create_memory_tool(self, context, payload):
        self.calls.append(("create_memory", payload))
        return {"id": "mem-1", "scope": payload["scope"], "content": payload["content"]}

    def supersede_memories_tool(self, context, payload):
        self.calls.append(("supersede", payload))
        if self.supersede_error:
            raise self.supersede_error
        return {"created": {}, "deactivated_ids": []}

    def of(self, name):
        return [arg for call, arg in self.calls if call == name]


class FixedEmbedder:
    def embed(self, text, *, task):
        return [0.5] * EMBEDDING_DIM


class BrokenEmbedder:
    def embed(self, text, *, task):
        raise httpx.ConnectError("ollama not running")


def _memory(tools, embedder=None, summarizer=None):
    return AgentMemory(embedder=embedder or NullEmbedder(), summarizer=summarizer, tools=tools, background=InlineExecutor())


def test_fetch_context_combines_summary_and_facts() -> None:
    tools = FakeMemoryTools(
        summary="User manages the Lahore depot.",
        facts=[
            {"scope": "personal", "content": "Prefers PKR", "entity_id": None, "entity_type": None},
            {"scope": "entity", "content": "Transmission replaced", "entity_id": "v1", "entity_type": "vehicle"},
        ],
    )
    text = _memory(tools).fetch_context(CTX, "s1", "what about ABC-123?")

    assert "User manages the Lahore depot." in text
    assert "- [personal] Prefers PKR" in text
    assert "- [vehicle v1] Transmission replaced" in text


def test_fetch_context_uses_embedding_when_available() -> None:
    tools = FakeMemoryTools()
    _memory(tools, embedder=FixedEmbedder()).fetch_context(CTX, None, "fuel policy?")
    payload = tools.of("search")[0]
    assert len(payload["embedding"]) == EMBEDDING_DIM
    assert "query_text" not in payload


def test_fetch_context_falls_back_to_keywords_when_embedder_fails() -> None:
    tools = FakeMemoryTools()
    _memory(tools, embedder=BrokenEmbedder()).fetch_context(CTX, None, "fuel policy?")
    payload = tools.of("search")[0]
    assert payload["query_text"] == "fuel policy?"
    assert "embedding" not in payload


def test_fetch_context_returns_none_when_nothing_is_remembered() -> None:
    assert _memory(FakeMemoryTools()).fetch_context(CTX, "s1", "hi") is None


def test_save_memory_embeds_as_document_and_drops_nulls() -> None:
    tools = FakeMemoryTools()
    _memory(tools, embedder=FixedEmbedder()).save_memory(
        CTX, {"content": "Prefers PKR", "scope": "personal", "entity_id": None, "entity_type": None}
    )
    payload = tools.of("create_memory")[0]
    assert payload["content"] == "Prefers PKR"
    assert "entity_id" not in payload
    assert len(payload["embedding"]) == EMBEDDING_DIM


def test_record_message_triggers_summarization_when_backend_asks() -> None:
    enqueued = []

    class _Summarizer:
        def enqueue(self, context, session_id, *, executor):
            enqueued.append(session_id)

    tools = FakeMemoryTools(needs_summarization=True)
    _memory(tools, summarizer=_Summarizer()).record_message(CTX, "s1", "user", "hello").result()
    assert tools.of("append") == [("user", "hello")]
    assert enqueued == ["s1"]


def test_record_message_failure_is_swallowed() -> None:
    class _Down(FakeMemoryTools):
        def append_message_tool(self, *args):
            raise BackendAPIError(503, "down")

    _memory(_Down()).record_message(CTX, "s1", "user", "hello").result()  # must not raise


def test_on_write_supersedes_each_fact() -> None:
    tools = FakeMemoryTools()
    future = _memory(tools, embedder=FixedEmbedder()).on_write(
        "accountability",
        {"created_record": {"vehicle_id": "v1", "driver_id": "d1", "severity": "minor", "incident_type": "damage", "date": "d", "description": "scratch"}},
        CTX,
    )
    future.result()
    payloads = tools.of("supersede")
    assert {(p["entity_type"], p["entity_id"]) for p in payloads} == {("vehicle", "v1"), ("driver", "d1")}
    assert all(len(p["embedding"]) == EMBEDDING_DIM for p in payloads)


def test_on_write_swallows_rbac_rejection() -> None:
    tools = FakeMemoryTools(supersede_error=BackendAPIError(403, "Role 'driver' cannot write entity memories"))
    future = _memory(tools).on_write("maintenance", {"maintenance_log": {"vehicle_id": "v1", "service_type": "oil_change"}}, CTX)
    future.result()  # must not raise


def test_on_write_ignores_writes_without_entity_facts() -> None:
    tools = FakeMemoryTools()
    assert _memory(tools).on_write("fuel", {"created_record": {"id": "f1"}}, CTX) is None
    assert tools.calls == []
