import pytest

from tools.safety_hooks import UnsafeSQLError, pre_tool_call


def test_allows_select() -> None:
    sql = "SELECT * FROM vehicles WHERE id = 1"
    assert pre_tool_call(sql) == sql


def test_allows_cte() -> None:
    sql = "WITH recent AS (SELECT * FROM trip_logs) SELECT * FROM recent"
    assert pre_tool_call(sql) == sql


def test_blocks_insert() -> None:
    with pytest.raises(UnsafeSQLError):
        pre_tool_call("INSERT INTO vehicles (name) VALUES ('x')")


def test_blocks_delete() -> None:
    with pytest.raises(UnsafeSQLError):
        pre_tool_call("DELETE FROM vehicles")


def test_blocks_drop_disguised_as_select() -> None:
    with pytest.raises(UnsafeSQLError):
        pre_tool_call("SELECT * FROM vehicles; DROP TABLE vehicles;")


def test_blocks_empty() -> None:
    with pytest.raises(UnsafeSQLError):
        pre_tool_call("   ")
