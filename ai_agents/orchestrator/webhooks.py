"""AlertDispatcher: rule-based "Real-World Alert" post-hook, per
execution-post_hooks.md §3.

Mirrors FleetLiveObserver's shape (orchestrator/callbacks.py) deliberately:
same attach_queue/run_worker async-drain pattern, same "never break the
caller" try/except-everywhere discipline, same honest default sink (no
webhook endpoint exists anywhere in this codebase or docker-compose.yml --
`log_sink` logs via `logging.getLogger("fleet.alerts")` until a real one is
configured, swappable via the same Callable interface).

Two corrections to the spec's own rule bodies, found while reading the real
backend schemas (backend/app/schemas/*.py) rather than trusting the spec's
field names:

1. Maintenance: the spec's rule (`raw_result.get("stock_remaining", 999) <
   raw_result.get("minimum_threshold", 0)`) references fields that do not
   exist anywhere in this backend. The real fields are `qty_on_hand` and
   `reorder_threshold` (backend/app/schemas/inventory.py's
   PartsInventoryBase/PartsInventoryResponse), and they show up in TWO
   different shapes depending on which maintenance flow ran:
     - inventory_restock: `updated_parts` is a list of raw
       PartsInventoryResponse dicts (qty_on_hand/reorder_threshold at the
       top level of each item) -- agents/maintenance/graph.py's restocking
       node stores exactly what update_inventory_tool returns.
     - maintenance_onboard: `mechanic_report.low_stock_alerts` is a list of
       LowStockAlert dicts (backend/app/schemas/maintenance.py), which only
       carry `part_id` + a `low_stock_alert: bool` flag -- no raw
       quantities at all, so this shape can't be scanned for
       qty_on_hand/reorder_threshold and needs its own check.
2. Accountability: the spec's rule checks
   `raw_result.get("incident_severity") in ["High", "Critical"]`, but the
   real field is `severity` (backend/app/schemas/accountability.py's
   IncidentLogResponse), and IncidentSeverity
   (backend/app/models/enums.py) is `minor|moderate|severe|critical`, all
   lowercase -- there is no "High" value in this system at all. The real
   rule fires on the two most serious real values, `severe`/`critical`.
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from datetime import datetime, timezone
from typing import Any, Awaitable, Callable

from pydantic import BaseModel, ConfigDict, Field

logger = logging.getLogger("fleet.alerts")


class Alert(BaseModel):
    model_config = ConfigDict(extra="forbid")

    alert_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    organization_id: str
    agent_name: str
    rule: str
    payload: dict[str, Any]
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


AlertSink = Callable[[Alert], Awaitable[None]]


async def log_sink(alert: Alert) -> None:
    """Default sink -- see module docstring. No webhook endpoint exists to
    POST to yet; this is the same honest-stub treatment as
    callbacks.py's log_sink."""
    logger.warning("alert: %s", alert.model_dump(mode="json"))


def _iter_dicts(value: Any):
    """Recursively yields every nested dict inside value (dicts and lists),
    so a low-stock part can be found regardless of which agent's
    raw_result shape it's nested in."""
    if isinstance(value, dict):
        yield value
        for item in value.values():
            yield from _iter_dicts(item)
    elif isinstance(value, list):
        for item in value:
            yield from _iter_dicts(item)


def _find_low_stock_parts(raw_result: dict[str, Any]) -> list[dict[str, Any]]:
    """Scans for any nested dict carrying BOTH real inventory fields
    (qty_on_hand, reorder_threshold) where the quantity has dropped at or
    below the reorder point -- covers restocking's `updated_parts`."""
    hits = []
    for candidate in _iter_dicts(raw_result):
        qty = candidate.get("qty_on_hand")
        threshold = candidate.get("reorder_threshold")
        if isinstance(qty, (int, float)) and isinstance(threshold, (int, float)) and qty <= threshold:
            hits.append(candidate)
    return hits


def _maintenance_rule(raw_result: dict[str, Any]) -> list[dict[str, Any]]:
    """Combines the low-stock scan with maintenance_onboard's own
    low_stock_alerts flags (see module docstring point 1) -- either shape
    is enough to fire."""
    hits = _find_low_stock_parts(raw_result)
    mechanic_report = raw_result.get("mechanic_report") or {}
    for alert in mechanic_report.get("low_stock_alerts") or []:
        if isinstance(alert, dict) and alert.get("low_stock_alert"):
            hits.append(alert)
    return hits


_CRITICAL_SEVERITIES = frozenset({"severe", "critical"})


def _accountability_rule(raw_result: dict[str, Any]) -> dict[str, Any] | None:
    record = raw_result.get("created_record") or {}
    severity = str(record.get("severity") or "").lower()
    return record if severity in _CRITICAL_SEVERITIES else None


class AlertDispatcher:
    """Injectable on OrchestratorDeps, same pattern as FleetLiveObserver --
    defaults to None there so every pre-existing test keeps passing
    unmodified."""

    def __init__(self, *, sink: AlertSink = log_sink) -> None:
        self.sink = sink
        self.alerts: list[Alert] = []
        self._queue: asyncio.Queue | None = None

    def attach_queue(self, queue: asyncio.Queue) -> None:
        """Opt-in, mirrors FleetLiveObserver.attach_queue -- only needed by
        an async caller draining alerts concurrently via run_worker."""
        self._queue = queue

    async def run_worker(self, queue: asyncio.Queue, *, batch_size: int = 20) -> None:
        while True:
            batch = [await queue.get()]
            while len(batch) < batch_size and not queue.empty():
                batch.append(queue.get_nowait())
            for alert in batch:
                await self._safe_sink(alert)
            for _ in batch:
                queue.task_done()

    async def _safe_sink(self, alert: Alert) -> None:
        try:
            await self.sink(alert)
        except Exception:  # noqa: BLE001 -- alert dispatch must never break the caller
            logger.exception("AlertDispatcher: sink failed for alert_id=%s", alert.alert_id)

    def evaluate_and_queue(self, agent_name: str, raw_result: dict[str, Any], organization_id: str) -> list[Alert]:
        """Sync entry point graph.py's execute_tool calls directly after a
        tool returns raw_result -- zero LLM cost, pure rule evaluation.
        Never raises: a bad/missing field must never break tool execution."""
        try:
            fired: list[Alert] = []
            if agent_name == "maintenance":
                for part in _maintenance_rule(raw_result):
                    fired.append(Alert(organization_id=organization_id, agent_name=agent_name, rule="low_stock", payload=part))
            elif agent_name == "accountability":
                record = _accountability_rule(raw_result)
                if record is not None:
                    fired.append(
                        Alert(organization_id=organization_id, agent_name=agent_name, rule="critical_incident", payload=record)
                    )
            for alert in fired:
                self._queue_alert(alert)
            return fired
        except Exception:  # noqa: BLE001
            logger.exception("AlertDispatcher: rule evaluation failed for agent_name=%r", agent_name)
            return []

    def _queue_alert(self, alert: Alert) -> None:
        self.alerts.append(alert)
        if self._queue is not None:
            self._queue.put_nowait(alert)
        else:
            # No async queue attached (the sync graph path) -- log inline
            # rather than silently dropping the alert.
            logger.warning("alert (sync path): %s", alert.model_dump(mode="json"))
