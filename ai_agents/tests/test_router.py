from agents.foundation.router import classify_intent


def test_image_present_classifies_as_onboard() -> None:
    state = classify_intent({"image_bytes": b"jpeg-bytes"})
    assert state["intent"] == "onboard"
    assert state["stage"] == "extracting"


def test_no_image_classifies_as_query() -> None:
    state = classify_intent({"query_text": "list my vehicles"})
    assert state["intent"] == "query"
    assert state["stage"] == "querying"
