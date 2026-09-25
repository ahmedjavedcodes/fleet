"""Stock-sufficiency guardrail for the Maintenance Agent.

Per maintenance-inventory-agent.md FR 5 / AC 2: halts a maintenance
onboarding before create_mechanic_report_tool when a requested part
quantity exceeds qty_on_hand. This is a fail-fast UX layer only --
backend/app/services/inventory_service.py's decrement_stock_for_parts_used
is the real authority: it row-locks each part (SELECT ... FOR UPDATE) and
returns 400 "Insufficient stock" if a decrement would go negative, so a
race between this pre-check and the report call is still possible (see
graph.py's handling of that 400 response, AC 3).
"""

from __future__ import annotations

from typing import Any


class StockDeficitError(Exception):
    """Raised when a resolved part's requested qty exceeds its qty_on_hand."""


def check_stock_sufficient(resolved_parts: list[dict[str, Any]], inventory: list[dict[str, Any]]) -> None:
    """resolved_parts: [{"part_id": ..., "qty": ...}, ...].
    inventory: get_inventory_tool's response (each row has "id", "qty_on_hand", "name").

    Raises StockDeficitError naming the first deficit found.
    """
    by_id = {part["id"]: part for part in inventory}

    for item in resolved_parts:
        part = by_id.get(item["part_id"])
        if part is None:
            raise StockDeficitError(f"Part {item['part_id']} is no longer in inventory.")
        if part["qty_on_hand"] < item["qty"]:
            raise StockDeficitError(
                f"Insufficient stock for {part.get('name', item['part_id'])}: "
                f"need {item['qty']}, have {part['qty_on_hand']}."
            )
