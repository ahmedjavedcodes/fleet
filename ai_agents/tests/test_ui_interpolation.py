from orchestrator.ui_interpolation import HITL_PAUSE_MESSAGE, interpolate_node, interpolate_tool_start


def test_plan_node_message() -> None:
    assert interpolate_node("plan") == "Thinking and planning next steps..."


def test_synthesize_node_message() -> None:
    assert interpolate_node("synthesize") == "Drafting final response..."


def test_unknown_node_falls_back_to_generic() -> None:
    assert interpolate_node("some_future_node") == "Working on it..."


def test_assignment_tool_interpolates_vehicle_id() -> None:
    assert interpolate_tool_start("assignment", {"query_vehicle_id": "ABC-123"}) == "Checking assignment rules for ABC-123..."


def test_assignment_tool_missing_arg_falls_back_to_generic_noun() -> None:
    assert interpolate_tool_start("assignment", {}) == "Checking assignment rules for vehicle..."


def test_foundation_tool_interpolates_query_entity() -> None:
    assert interpolate_tool_start("foundation", {"query_entity": "drivers"}) == "Searching fleet registry for drivers..."


def test_maintenance_tool_interpolates_query_entity() -> None:
    assert interpolate_tool_start("maintenance", {"query_entity": "low_stock"}) == "Verifying maintenance inventory for low_stock..."


def test_fuel_tool_has_static_message() -> None:
    assert interpolate_tool_start("fuel", {}) == "Auditing fuel and trip logs..."


def test_unknown_tool_falls_back_to_generic() -> None:
    assert interpolate_tool_start("some_future_tool", {"anything": True}) == "Working on it..."


def test_hitl_pause_message_is_exact() -> None:
    assert HITL_PAUSE_MESSAGE == "Action paused: Waiting for your approval."


def test_write_calls_and_the_non_agent_tools_get_specific_strings() -> None:
    from orchestrator.ui_interpolation import interpolate_tool_start

    assert interpolate_tool_start("fuel", {"trip_fields": {"vehicle_id": "v1"}}) == "Logging the trip..."
    assert interpolate_tool_start("fuel", {"fuel_fields": {"slip_id": "S1"}}) == "Recording the fuel log..."
    assert interpolate_tool_start("accountability", {"document_type": "incident_report"}) == "Filing the incident report..."
    assert interpolate_tool_start("search_documents", {"query": "tyre pressure"}) == "Searching uploaded documents..."
    assert interpolate_tool_start("update_memory", {"content": "x"}) == "Preparing a note to remember..."
