"""add dashboard query indexes

Revision ID: a7c3e91b4d20
Revises: 55cad156abd5
Create Date: 2026-10-01 12:00:00.000000

Indexes for the filters the dashboard, the trend queries and the warnings feed run on every load, which became
visible with tens of thousands of rows. incident_logs.resolution_status is the incident's status; maintenance_logs has
no status column (overdue/upcoming is derived from next_due_km/next_due_date), so its date columns are indexed instead.
"""
from typing import Sequence, Union

from alembic import op

revision: str = "a7c3e91b4d20"
down_revision: Union[str, None] = "55cad156abd5"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

INDEXES = [
    ("ix_fuel_logs_org_date", "fuel_logs", ["organization_id", "date"]),
    ("ix_fuel_logs_vehicle_date", "fuel_logs", ["vehicle_id", "date"]),
    ("ix_maintenance_logs_org_date", "maintenance_logs", ["organization_id", "date"]),
    ("ix_maintenance_logs_vehicle_date", "maintenance_logs", ["vehicle_id", "date"]),
    ("ix_maintenance_logs_org_next_due_date", "maintenance_logs", ["organization_id", "next_due_date"]),
    ("ix_incident_logs_org_status_severity", "incident_logs", ["organization_id", "resolution_status", "severity"]),
    ("ix_incident_logs_vehicle_date", "incident_logs", ["vehicle_id", "date"]),
]


def upgrade() -> None:
    for name, table, columns in INDEXES:
        op.create_index(name, table, columns, unique=False)


def downgrade() -> None:
    for name, table, _ in reversed(INDEXES):
        op.drop_index(name, table_name=table)
