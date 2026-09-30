import pytest

from orchestrator.turn_profile import classify_turn


@pytest.mark.parametrize(
    "message",
    [
        "How many vehicles do we have?",
        "What's the fuel efficiency of ABC-123?",
        "Show fuel trends for the last 6 months",
        "list overdue maintenance",
        "Which drivers had incidents this month?",
        "Can you check the dashboard summary?",
        "Compare fuel cost per km across the fleet",
    ],
)
def test_plain_reads_take_the_fast_path(message: str) -> None:
    assert classify_turn(message) == "read"


@pytest.mark.parametrize(
    "message",
    [
        "Log a trip for ABC-123 from 45000 to 45250 km",
        "Assign ABC-123 to Jane",
        "Remember that I prefer amounts in PKR",
        "What should I do? Please report an incident on ABC-123",  # a read lead, but it writes
        "Update the odometer for ABC-123",
        "From now on show costs in PKR",
        "ABC-123 needs a brake check",  # not phrased as a lookup: be conservative
        "",
    ],
)
def test_writes_memory_and_ambiguous_turns_take_the_full_path(message: str) -> None:
    assert classify_turn(message) == "full"


def test_an_attachment_always_takes_the_full_path() -> None:
    assert classify_turn("What is this?", has_attachment=True) == "full"
