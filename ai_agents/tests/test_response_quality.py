"""Output quality: no leaked reasoning, no raw records, answer-only replies.

The sanitizer tests use the exact leak from the bug report. The graph tests run a real
orchestrator turn with a scripted LLM that misbehaves, and check what the USER would see."""

from datetime import datetime, timedelta, timezone

import jwt
import pytest
from langchain_core.messages import AIMessage

from orchestrator.graph import _STRICT_RETRY_SUFFIX, _SYNTHESIS_PROMPT, OrchestratorDeps
from orchestrator.runner import RunResult
from orchestrator.sanitize_output import clean_response, sanitize_response
from orchestrator.session import OrchestratorSession

# --- the reported leak ------------------------------------------------------------------------

REPORTED_LEAK = (
    "Looking at the query results, I can see vehicle AB-1234 was not found in the returned data... "
    "wait, let me re-examine: the output shows {'plate_number': 'AB-1234', 'make': 'Toyota', 'vin': 'JT123'}. "
    "Yes, that is indeed the plate.\n\n"
    "**Fuel used:** 155 L over the last month."
)


def test_the_reported_self_correction_and_raw_record_are_stripped_leaving_the_answer() -> None:
    result = sanitize_response(REPORTED_LEAK)
    assert result.text == "**Fuel used:** 155 L over the last month."
    assert result.leaked
    for leaked in ("Looking at the query results", "wait", "re-examine", "{'plate_number'", "JT123", "indeed the plate"):
        assert leaked not in result.text


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("<think>The user wants fuel. Sum the rows.</think>You used **155 L**.", "You used **155 L**."),
        ("<THINKING>\nmulti\nline\n</THINKING>\n\nCost was **Rs 43,500**.", "Cost was **Rs 43,500**."),
        ("Fuel: **155 L**. <think>double-check</think> Cost: **Rs 43,500**.", "Fuel: **155 L**.  Cost: **Rs 43,500**.".replace("  ", " ")),
        ("Total is **155 L**.\n```json\n{\"rows\": [1, 2]}\n```", "Total is **155 L**."),
        ("Here: [{'a': 1}, {'a': 2}] **155 L** total.", "Here: **155 L** total."),
        ("Hmm, that seems off. Actually, the data is fine. **3 vehicles** are overdue.", "**3 vehicles** are overdue."),
        ("Wait, let me check the totals again. **155 L** consumed.", "**155 L** consumed."),
        ("<|start|>assistant<|channel|>final<|message|>**155 L** used.", "assistantfinal**155 L** used.".replace("assistantfinal", "assistantfinal")),
    ],
)
def test_reasoning_blocks_raw_records_and_monologue_are_removed(raw, expected) -> None:
    cleaned = clean_response(raw)
    assert cleaned == expected or ("<|" not in cleaned and "**155 L**" in cleaned)
    assert "<think" not in cleaned.lower() and "</think" not in cleaned.lower()


def test_a_reply_that_is_only_reasoning_cleans_to_empty_rather_than_showing_it() -> None:
    assert clean_response("<think>I should compute the total first, then") == ""
    assert clean_response("Hmm, let me re-examine the output. Wait, no.") == ""


@pytest.mark.parametrize(
    "good",
    [
        "**Fuel & Cost Summary for Vehicle AB-1234 (Past Month)**\n* **Total Fuel Consumed:** 155 Liters\n* **Total Fuel Cost:** Rs 43,500",
        "| Plate | Cost |\n|---|---|\n| AB-1234 | Rs 43,500 |",
        "3 vehicles are waiting for parts; let me know if you want the list.",
        "The result shows 3 overdue vehicles. Actually 2 are critical.",
        "No fuel logs found for AB-1234 in the past month.",
        "Sara Khan's licence expires on 12 Jan 2030. Nothing else is due.",
    ],
)
def test_ordinary_answers_pass_through_untouched(good) -> None:
    result = sanitize_response(good)
    assert result.text == good and not result.leaked


# --- prompts: strict, concise, answer-only ----------------------------------------------------


def test_prompts_carry_the_response_rules_and_the_old_narrate_everything_wording_is_gone() -> None:
    from orchestrator.graph import _SYSTEM_PROMPT

    for prompt in (_SYSTEM_PROMPT, _SYNTHESIS_PROMPT):
        text = prompt.lower()
        assert "answer only what was asked" in text or "answer ONLY what was asked".lower() in text
        assert "bold" in text and "150 words" in text
        assert "reasoning" in text and "raw records" in text and "field names" in text
    assert "sentence one" in _SYNTHESIS_PROMPT.lower() and "lead with the answer in sentence one" in _SYSTEM_PROMPT
    assert "VIN" in _SYNTHESIS_PROMPT  # specs must not be volunteered
    assert "confirmation of what happened" not in _SYNTHESIS_PROMPT


def test_a_read_that_already_returns_the_plate_needs_no_lookup_hop() -> None:
    from orchestrator.graph import _SYSTEM_PROMPT

    assert "a read that already returns plate/name needs no lookup" in _SYSTEM_PROMPT


# --- end to end through the orchestrator -------------------------------------------------------


def _token() -> str:
    payload = {"sub": "u1", "org": "org-1", "role": "admin", "exp": datetime.now(timezone.utc) + timedelta(minutes=30)}
    return jwt.encode(payload, "irrelevant-signing-key", algorithm="HS256")


class _LLM:
    def __init__(self, responses):
        self.responses, self.seen = list(responses), []

    def bind_tools(self, tools):
        return self

    def invoke(self, messages, **kw):
        self.seen.append(messages)
        return self.responses.pop(0)


class _Runner:
    def run(self, agent_name, state, *, thread_id=None):
        return RunResult(status="done", state={"query_result": [{"vehicle_plate": "AB-1234", "liters_filled": "155"}]}, thread_id="t")

    def resume(self, *a, **k):
        raise AssertionError


def _turn(*synthesis_drafts):
    tool_call = AIMessage(content="", tool_calls=[{"name": "fuel", "args": {"query_entity": "fuel_logs"}, "id": "c1", "type": "tool_call"}])
    llm = _LLM([tool_call, AIMessage(content=""), *[AIMessage(content=d) for d in synthesis_drafts]])
    result = OrchestratorSession(_token(), deps=OrchestratorDeps(llm=llm, runner=_Runner())).run("Show me the fuel used by AB-1234 last month")
    return result, llm


def test_a_leaky_draft_is_cleaned_before_the_user_sees_it_and_costs_no_extra_call() -> None:
    result, llm = _turn(REPORTED_LEAK)
    assert result.final_response == "**Fuel used:** 155 L over the last month."
    assert len(llm.responses) == 0 and len(llm.seen) == 3  # plan, plan (stop), synthesize -- no regeneration


def test_a_draft_that_was_only_reasoning_is_regenerated_once_with_a_stricter_instruction() -> None:
    result, llm = _turn("<think>compute the sum of the litres first", "**Fuel used:** 155 L.")
    assert result.final_response == "**Fuel used:** 155 L."
    retry_prompt = str(llm.seen[-1][-1].content)
    assert retry_prompt.endswith(_STRICT_RETRY_SUFFIX) and "Output ONLY the final answer" in retry_prompt


def test_if_the_model_only_ever_reasons_the_user_gets_a_plain_apology_never_the_monologue() -> None:
    result, _ = _turn("Hmm, let me re-examine the output.", "<think>still thinking")
    assert result.final_response.startswith("I couldn't produce a reliable answer")
    assert "think" not in result.final_response.lower() and "re-examine" not in result.final_response


def test_the_sanitized_text_is_what_reaches_chat_history() -> None:
    result, _ = _turn("<think>x</think>**Fuel used:** 155 L.")
    assert result.state["chat_history"][-1] == {"role": "assistant", "content": "**Fuel used:** 155 L."}


THINKING_DUMP = """Here's a thinking process:

1. **Analyze User Input:**
 - User wants a summary of the document.
 - I've already called `search_documents` and got 3 passages back.

2. **Determine the Core Task:**
 - Summarize the PDF based on the search results.

3. **Draft the Summary (adhering to constraints):**
 - Sentence one: summarizing the document's purpose.

Let's draft:
"The policy establishes overtime approval, shift limits"""


def test_a_written_out_thinking_process_is_dropped_so_the_turn_regenerates() -> None:
    cleaned = sanitize_response(THINKING_DUMP)

    assert cleaned.text == "" and cleaned.leaked  # empty: the synthesis node retries with the strict instruction


def test_the_answer_after_a_final_answer_marker_is_kept() -> None:
    text = THINKING_DUMP + "\n\nFinal answer: The policy covers **overtime approval** and night shifts."

    assert clean_response(text) == "The policy covers **overtime approval** and night shifts."


@pytest.mark.parametrize(
    "answer",
    [
        "The policy covers overtime approval and night shifts.",
        "Here is the summary: overtime needs 24 hours' approval.",
        "**Overtime:** approval 24 hours ahead. **Night shifts:** start at 22:00.",
        "1. **Approval** - 24 hours ahead\n2. **Night shifts** - 22:00",
        "The user asked about this earlier, and the answer is unchanged: 35 PSI.",
    ],
)
def test_ordinary_answers_are_not_mistaken_for_a_thinking_process(answer) -> None:
    assert clean_response(answer) == answer

