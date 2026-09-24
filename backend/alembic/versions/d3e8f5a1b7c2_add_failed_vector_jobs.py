"""add_failed_vector_jobs

Revision ID: d3e8f5a1b7c2
Revises: c7a41e2d9f10
Create Date: 2026-09-24 15:30:00.000000

Dead-letter queue for Pinecone writes that failed every retry
(Pinecone_Migration_Hardened.md §3).
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = 'd3e8f5a1b7c2'
down_revision: Union[str, None] = 'c7a41e2d9f10'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table('failed_vector_jobs',
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('payload', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('error_message', sa.Text(), nullable=False),
    sa.Column('attempts', sa.Integer(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('organization_id', sa.UUID(), nullable=False),
    sa.ForeignKeyConstraint(['organization_id'], ['organizations.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_failed_vector_jobs_organization_id'), 'failed_vector_jobs', ['organization_id'], unique=False)


def downgrade() -> None:
    op.drop_index(op.f('ix_failed_vector_jobs_organization_id'), table_name='failed_vector_jobs')
    op.drop_table('failed_vector_jobs')
