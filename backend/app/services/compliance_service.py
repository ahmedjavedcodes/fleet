import uuid
from datetime import datetime, timezone

from fastapi import HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models.enums import ServiceType, VehicleStatus
from app.models.maintenance import ComplianceRule, MaintenanceLog, MaintenanceLogService
from app.models.vehicle import Vehicle
from app.schemas.compliance import (
    ComplianceRuleCreate,
    ComplianceRuleResponse,
    ComplianceRuleUpdate,
    ComplianceStatusItem,
    VehicleComplianceResponse,
)
from app.services.maintenance_service import _add_months, _get_vehicle_or_404

_DUPLICATE_RULE_ERROR = HTTPException(
    status_code=status.HTTP_409_CONFLICT,
    detail="A compliance rule for this vehicle_make/vehicle_model/service_type already exists",
)


def create_rule(db: Session, org_id: uuid.UUID, data: ComplianceRuleCreate, created_by: uuid.UUID) -> ComplianceRule:
    rule = ComplianceRule(id=uuid.uuid4(), organization_id=org_id, created_by=created_by, **data.model_dump())
    db.add(rule)
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise _DUPLICATE_RULE_ERROR from exc
    db.refresh(rule)
    return rule


def get_rule(db: Session, org_id: uuid.UUID, rule_id: uuid.UUID) -> ComplianceRule:
    rule = db.execute(
        select(ComplianceRule).where(
            ComplianceRule.id == rule_id, ComplianceRule.organization_id == org_id, ComplianceRule.is_deleted.is_(False)
        )
    ).scalar_one_or_none()
    if rule is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Compliance rule not found")
    return rule


def list_rules(
    db: Session,
    org_id: uuid.UUID,
    *,
    vehicle_make: str | None = None,
    vehicle_model: str | None = None,
    service_type: ServiceType | None = None,
) -> list[ComplianceRule]:
    stmt = select(ComplianceRule).where(ComplianceRule.organization_id == org_id, ComplianceRule.is_deleted.is_(False))
    if vehicle_make is not None:
        stmt = stmt.where(ComplianceRule.vehicle_make == vehicle_make)
    if vehicle_model is not None:
        stmt = stmt.where(ComplianceRule.vehicle_model == vehicle_model)
    if service_type is not None:
        stmt = stmt.where(ComplianceRule.service_type == service_type)
    return list(db.execute(stmt).scalars())


def update_rule(
    db: Session, org_id: uuid.UUID, rule_id: uuid.UUID, data: ComplianceRuleUpdate, updated_by: uuid.UUID
) -> ComplianceRule:
    rule = get_rule(db, org_id, rule_id)
    for field, value in data.model_dump(exclude_unset=True).items():
        setattr(rule, field, value)
    rule.updated_by = updated_by
    db.commit()
    db.refresh(rule)
    return rule


def evaluate_rule(
    interval_km: int, interval_months: int, current_odometer: int, last_date, last_odometer: int, today
) -> tuple[str, int, int]:
    """(status, km_remaining, days_remaining) of one compliance rule against a vehicle's last service of that type."""
    km_gap = current_odometer - last_odometer
    total_days = (_add_months(last_date, interval_months) - last_date).days
    elapsed_days = (today - last_date).days

    if km_gap > interval_km or elapsed_days > total_days:
        status_ = "overdue"
    # Integer-safe check for elapsed/total >= 0.8 (avoids float rounding
    # on the multiplication): elapsed*5 >= total*4  <=>  elapsed >= 0.8*total.
    elif km_gap * 5 >= interval_km * 4 or elapsed_days * 5 >= total_days * 4:
        status_ = "due_soon"
    else:
        status_ = "compliant"
    return status_, interval_km - km_gap, total_days - elapsed_days


def compliance_statuses_by_vehicle(db: Session, org_id: uuid.UUID, vehicles: list[Vehicle]) -> dict[uuid.UUID, list[str]]:
    """The compliance status of every applicable rule for each of `vehicles`, from three queries in total (the rules,
    and the latest service per vehicle and type) instead of a few per vehicle. Exactly get_vehicle_compliance's
    statuses; a vehicle with no applicable rule maps to []."""
    rules = list(
        db.execute(
            select(ComplianceRule).where(ComplianceRule.organization_id == org_id, ComplianceRule.is_deleted.is_(False))
        ).scalars()
    )
    rules_by_model: dict[tuple[str, str], list[ComplianceRule]] = {}
    for rule in rules:
        rules_by_model.setdefault((rule.vehicle_make, rule.vehicle_model), []).append(rule)
    if not rules_by_model:
        return {v.id: [] for v in vehicles}

    ranked = (
        select(
            MaintenanceLog.vehicle_id.label("vehicle_id"),
            MaintenanceLogService.service_type.label("service_type"),
            MaintenanceLog.date.label("date"),
            MaintenanceLog.odometer_at_service.label("odometer"),
            func.row_number()
            .over(
                partition_by=(MaintenanceLog.vehicle_id, MaintenanceLogService.service_type),
                order_by=(MaintenanceLog.date.desc(), MaintenanceLog.odometer_at_service.desc()),
            )
            .label("rn"),
        )
        .join(MaintenanceLogService, MaintenanceLogService.maintenance_log_id == MaintenanceLog.id)
        .where(MaintenanceLog.organization_id == org_id, MaintenanceLog.is_deleted.is_(False))
        .subquery()
    )
    latest = {
        (vehicle_id, service_type): (date_, odometer)
        for vehicle_id, service_type, date_, odometer in db.execute(
            select(ranked.c.vehicle_id, ranked.c.service_type, ranked.c.date, ranked.c.odometer).where(ranked.c.rn == 1)
        ).all()
    }

    today = datetime.now(timezone.utc).date()
    out: dict[uuid.UUID, list[str]] = {}
    for vehicle in vehicles:
        statuses: list[str] = []
        for rule in rules_by_model.get((vehicle.make, vehicle.model), []):
            last = latest.get((vehicle.id, rule.service_type))
            if last is None:
                statuses.append("never_performed")
            else:
                statuses.append(evaluate_rule(rule.interval_km, rule.interval_months, vehicle.current_odometer, last[0], last[1], today)[0])
        out[vehicle.id] = statuses
    return out


def get_vehicle_compliance(db: Session, org_id: uuid.UUID, vehicle_id: uuid.UUID) -> VehicleComplianceResponse:
    """
    Read-only, computed fresh on every call -- never stored. For each
    ComplianceRule matching the vehicle's make/model: find the latest
    MaintenanceLog of that service_type; no such log -> 'never_performed'
    (treated as overdue); otherwise compare the km and time gap against the
    rule's interval.

    The spec states the time dimension as "months_gap > interval_months" but
    a fixed calendar interval doesn't divide evenly at the 80% due_soon
    threshold (e.g. 6 months * 0.8 = 4.8 months), so the equivalent day-based
    ratio is used instead: elapsed_days / total_days (where total_days is the
    day-span from the last service to its calendar-accurate due date) against
    the same 0.8 threshold. This is the same comparison in a unit that
    divides cleanly, not a different rule.

    Boundaries (see specs/03 EC-6/EC-7, confirmed against the acceptance
    criteria over the plan's own pseudocode where they conflicted): exactly at
    the 80% threshold is 'due_soon' (>=), exactly at 100% is NOT yet 'overdue'
    (only strictly greater than the interval counts).
    """
    vehicle = _get_vehicle_or_404(db, org_id, vehicle_id)

    rules = list(
        db.execute(
            select(ComplianceRule).where(
                ComplianceRule.organization_id == org_id,
                ComplianceRule.is_deleted.is_(False),
                ComplianceRule.vehicle_make == vehicle.make,
                ComplianceRule.vehicle_model == vehicle.model,
            )
        ).scalars()
    )

    today = datetime.now(timezone.utc).date()
    items: list[ComplianceStatusItem] = []

    for rule in rules:
        last_service = db.execute(
            select(MaintenanceLog)
            .join(MaintenanceLogService, MaintenanceLogService.maintenance_log_id == MaintenanceLog.id)
            .where(
                MaintenanceLog.organization_id == org_id,
                MaintenanceLog.is_deleted.is_(False),
                MaintenanceLog.vehicle_id == vehicle.id,
                MaintenanceLogService.service_type == rule.service_type,
            )
            .order_by(MaintenanceLog.date.desc(), MaintenanceLog.odometer_at_service.desc())
            .limit(1)
        ).scalar_one_or_none()

        rule_response = ComplianceRuleResponse.model_validate(rule)

        if last_service is None:
            items.append(
                ComplianceStatusItem(
                    rule=rule_response, status="never_performed", km_remaining=None, days_remaining=None, last_service_date=None
                )
            )
            continue

        compliance_status, km_remaining, days_remaining = evaluate_rule(
            rule.interval_km, rule.interval_months, vehicle.current_odometer, last_service.date, last_service.odometer_at_service, today
        )
        items.append(
            ComplianceStatusItem(
                rule=rule_response,
                status=compliance_status,
                km_remaining=km_remaining,
                days_remaining=days_remaining,
                last_service_date=last_service.date,
            )
        )

    return VehicleComplianceResponse(vehicle_id=vehicle.id, items=items)


def get_fleet_compliance_matrix(db: Session, org_id: uuid.UUID) -> list[VehicleComplianceResponse]:
    """Calls get_vehicle_compliance for every non-retired vehicle in the org.
    For fleet sizes in the dozens this is fine as N sequential calls; if it
    becomes a bottleneck, batch the 'latest MaintenanceLog per (vehicle,
    service_type)' query once for all vehicles instead -- don't pre-optimize
    this before it's measured."""
    vehicles = list(
        db.execute(
            select(Vehicle).where(
                Vehicle.organization_id == org_id,
                Vehicle.is_deleted.is_(False),
                Vehicle.status != VehicleStatus.retired,
            )
        ).scalars()
    )
    return [get_vehicle_compliance(db, org_id, v.id) for v in vehicles]
