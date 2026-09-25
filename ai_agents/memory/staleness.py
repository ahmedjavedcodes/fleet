"""Turns a successful sub-agent write into entity facts for the staleness
post-hook (agent-memory.md §3). Deterministic -- no LLM decides what gets
written here; the facts are derived from records a human already approved
through the sub-agent's own HITL gate."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal


@dataclass(frozen=True)
class EntityFact:
    entity_type: Literal["vehicle", "driver"]
    entity_id: str
    content: str


def _maintenance_facts(raw_result: dict[str, Any]) -> list[EntityFact]:
    log = raw_result.get("maintenance_log") or {}
    if not log.get("vehicle_id"):
        return []
    service = str(log.get("service_type") or "service").replace("_", " ")
    details = f": {log['description']}" if log.get("description") else ""
    when = f" on {log['date']}" if log.get("date") else ""
    odometer = f" at {log['odometer_at_service']} km" if log.get("odometer_at_service") else ""
    return [EntityFact("vehicle", str(log["vehicle_id"]), f"Maintenance{when}{odometer} -- {service}{details}")]


def _accountability_facts(raw_result: dict[str, Any]) -> list[EntityFact]:
    record = raw_result.get("created_record") or {}
    if not record.get("vehicle_id"):
        return []
    content = (
        f"{str(record.get('severity') or '').capitalize()} {record.get('incident_type') or 'incident'}"
        f" on {record.get('date')}: {record.get('description') or 'no description'}"
    ).strip()
    facts = [EntityFact("vehicle", str(record["vehicle_id"]), content)]
    if record.get("driver_id"):
        facts.append(EntityFact("driver", str(record["driver_id"]), content))
    return facts


def _assignment_facts(raw_result: dict[str, Any]) -> list[EntityFact]:
    record = raw_result.get("created_record") or {}
    vehicle_id, driver_id = record.get("vehicle_id"), record.get("driver_id")
    if not vehicle_id or not driver_id:
        return []
    if record.get("released_at"):
        content = f"Custody: released by driver {driver_id} at {record['released_at']}"
    else:
        content = f"Custody: currently assigned to driver {driver_id} since {record.get('assigned_at')}"
    return [EntityFact("vehicle", str(vehicle_id), content)]


_EXTRACTORS = {
    "maintenance": _maintenance_facts,
    "accountability": _accountability_facts,
    "assignment": _assignment_facts,
}


def extract_entity_facts(agent_name: str, raw_result: dict[str, Any]) -> list[EntityFact]:
    """Agents with no entity-level state worth remembering (fuel logs,
    onboarding, read-only insights) produce nothing."""
    extractor = _EXTRACTORS.get(agent_name)
    return extractor(raw_result) if extractor else []
