from orchestrator.fact_check import check_response_against_scratchpad


class _ScriptedLLM:
    def __init__(self, reply: str):
        self._reply = reply
        self.invoke_calls = 0

    def invoke(self, messages):
        self.invoke_calls += 1

        class _Response:
            content = self._reply

        return _Response()


class _ExplodingLLM:
    def invoke(self, messages):
        raise RuntimeError("Groq is down")


def test_ac3_flags_hallucinated_number_not_in_scratchpad() -> None:
    llm = _ScriptedLLM("YES")
    result = check_response_against_scratchpad(llm, "[maintenance] repair cost=$50", "Repair cost $500")
    assert result is True


def test_grounded_response_passes() -> None:
    llm = _ScriptedLLM("NO")
    result = check_response_against_scratchpad(llm, "[maintenance] repair cost=$50", "Repair cost $50")
    assert result is False


def test_verdict_matching_is_case_insensitive_and_tolerates_whitespace() -> None:
    llm = _ScriptedLLM("  yes\n")
    assert check_response_against_scratchpad(llm, "scratch", "response") is True


def test_fails_open_on_checker_exception() -> None:
    llm = _ExplodingLLM()
    assert check_response_against_scratchpad(llm, "scratch", "response") is False


def test_empty_final_response_short_circuits_without_calling_llm() -> None:
    llm = _ScriptedLLM("YES")
    assert check_response_against_scratchpad(llm, "scratch", "") is False
    assert llm.invoke_calls == 0
