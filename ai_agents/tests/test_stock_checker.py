import pytest

from agents.maintenance.stock_checker import StockDeficitError, check_stock_sufficient

_INVENTORY = [
    {"id": "p1", "name": "Oil Filter", "qty_on_hand": 5},
    {"id": "p2", "name": "Brake Pad", "qty_on_hand": 0},
]


def test_sufficient_stock_passes() -> None:
    check_stock_sufficient([{"part_id": "p1", "qty": 2}], _INVENTORY)


def test_insufficient_stock_raises() -> None:
    with pytest.raises(StockDeficitError):
        check_stock_sufficient([{"part_id": "p2", "qty": 1}], _INVENTORY)


def test_exact_match_passes() -> None:
    check_stock_sufficient([{"part_id": "p1", "qty": 5}], _INVENTORY)


def test_unknown_part_raises() -> None:
    with pytest.raises(StockDeficitError):
        check_stock_sufficient([{"part_id": "unknown", "qty": 1}], _INVENTORY)


def test_multiple_parts_all_sufficient_passes() -> None:
    check_stock_sufficient([{"part_id": "p1", "qty": 1}], _INVENTORY)


def test_empty_parts_list_passes() -> None:
    check_stock_sufficient([], _INVENTORY)
