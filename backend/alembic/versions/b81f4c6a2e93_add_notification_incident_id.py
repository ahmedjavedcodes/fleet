"""add notifications.incident_id

Revision ID: b81f4c6a2e93
Revises: a7c3e91b4d20
Create Date: 2026-10-01 13:00:00.000000

Links a stored incident notification to its incident, so the warnings feed (which also derives entries from unresolved
incidents) does not list the same incident twice for a user who already has the stored notification.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "b81f4c6a2e93"
down_revision: Union[str, None] = "a7c3e91b4d20"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("notifications", sa.Column("incident_id", postgresql.UUID(as_uuid=True), nullable=True))
    op.create_foreign_key("fk_notifications_incident_id", "notifications", "incident_logs", ["incident_id"], ["id"], ondelete="SET NULL")
    op.create_index("ix_notifications_incident_id", "notifications", ["incident_id"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_notifications_incident_id", table_name="notifications")
    op.drop_constraint("fk_notifications_incident_id", "notifications", type_="foreignkey")
    op.drop_column("notifications", "incident_id")
