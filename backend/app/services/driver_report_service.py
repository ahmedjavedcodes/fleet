import uuid
from datetime import date as date_type

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.accountability import DriverReport
from app.models.enums import VehicleCondition
from app.schemas.accountability import DriverReportCreate


def create_driver_report(db: Session, org_id: uuid.UUID, data: DriverReportCreate, created_by: uuid.UUID) -> DriverReport:
    """Plain insert. No update function exists anywhere in this module -- not
    an oversight; it's what makes the audit trail trustworthy. A future
    'let drivers fix a typo' request needs a product decision revisiting
    backendPlan.md's accountability rationale, not a quick addition here."""
    report = DriverReport(id=uuid.uuid4(), organization_id=org_id, created_by=created_by, **data.model_dump())
    db.add(report)
    db.commit()
    db.refresh(report)
    return report


def get_driver_report(
    db: Session, org_id: uuid.UUID, report_id: uuid.UUID, driver_id_filter: uuid.UUID | None = None
) -> DriverReport:
    stmt = select(DriverReport).where(
        DriverReport.id == report_id, DriverReport.organization_id == org_id, DriverReport.is_deleted.is_(False)
    )
    if driver_id_filter is not None:
        stmt = stmt.where(DriverReport.driver_id == driver_id_filter)
    report = db.execute(stmt).scalar_one_or_none()
    if report is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Driver report not found")
    return report


def list_driver_reports(
    db: Session,
    org_id: uuid.UUID,
    *,
    driver_id: uuid.UUID | None = None,
    vehicle_id: uuid.UUID | None = None,
    condition: VehicleCondition | None = None,
    driver_id_filter: uuid.UUID | None = None,
) -> list[DriverReport]:
    stmt = select(DriverReport).where(DriverReport.organization_id == org_id, DriverReport.is_deleted.is_(False))
    if driver_id_filter is not None:
        stmt = stmt.where(DriverReport.driver_id == driver_id_filter)
    if driver_id is not None:
        stmt = stmt.where(DriverReport.driver_id == driver_id)
    if vehicle_id is not None:
        stmt = stmt.where(DriverReport.vehicle_id == vehicle_id)
    if condition is not None:
        stmt = stmt.where(DriverReport.vehicle_condition == condition)
    stmt = stmt.order_by(DriverReport.shift_date.desc())
    return list(db.execute(stmt).scalars())
