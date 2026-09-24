"""add_agent_memory_tables

Revision ID: c7a41e2d9f10
Revises: b00dd9359ef1
Create Date: 2026-09-24 10:00:00.000000

Requires the pgvector extension to be installable on the target server
(docker-compose uses the pgvector/pgvector:pg16 image for this reason). A
plain Postgres without pgvector fails here, loudly, by design.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from pgvector.sqlalchemy import Vector
from sqlalchemy.dialects import postgresql


revision: str = 'c7a41e2d9f10'
down_revision: Union[str, None] = 'b00dd9359ef1'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")

    agent_message_role = postgresql.ENUM('user', 'assistant', name='agent_message_role')
    memory_scope = postgresql.ENUM('personal', 'organization', 'entity', name='memory_scope')
    memory_entity_type = postgresql.ENUM('vehicle', 'driver', name='memory_entity_type')

    op.create_table('agent_sessions',
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('user_id', sa.UUID(), nullable=False),
    sa.Column('running_summary', sa.Text(), server_default='', nullable=False),
    sa.Column('summary_version', sa.Integer(), server_default='0', nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('organization_id', sa.UUID(), nullable=False),
    sa.ForeignKeyConstraint(['organization_id'], ['organizations.id'], ),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_agent_sessions_organization_id'), 'agent_sessions', ['organization_id'], unique=False)
    op.create_index(op.f('ix_agent_sessions_user_id'), 'agent_sessions', ['user_id'], unique=False)

    op.create_table('agent_messages',
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('session_id', sa.UUID(), nullable=False),
    sa.Column('role', agent_message_role, nullable=False),
    sa.Column('content', sa.Text(), nullable=False),
    sa.Column('is_summarized', sa.Boolean(), server_default='false', nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('clock_timestamp()'), nullable=False),
    sa.ForeignKeyConstraint(['session_id'], ['agent_sessions.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index('ix_agent_messages_session_unsummarized', 'agent_messages', ['session_id', 'is_summarized', 'created_at'], unique=False)

    op.create_table('semantic_memories',
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('scope', memory_scope, nullable=False),
    sa.Column('user_id', sa.UUID(), nullable=True),
    sa.Column('entity_id', sa.UUID(), nullable=True),
    sa.Column('entity_type', memory_entity_type, nullable=True),
    sa.Column('content', sa.Text(), nullable=False),
    sa.Column('embedding', Vector(768), nullable=True),
    sa.Column('is_active', sa.Boolean(), server_default='true', nullable=False),
    sa.Column('created_by', sa.UUID(), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('clock_timestamp()'), nullable=False),
    sa.Column('deactivated_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('organization_id', sa.UUID(), nullable=False),
    sa.CheckConstraint("scope != 'personal' OR user_id IS NOT NULL", name='ck_semantic_memories_personal_has_user'),
    sa.CheckConstraint("scope != 'entity' OR (entity_id IS NOT NULL AND entity_type IS NOT NULL)", name='ck_semantic_memories_entity_has_entity'),
    sa.ForeignKeyConstraint(['created_by'], ['users.id'], ),
    sa.ForeignKeyConstraint(['organization_id'], ['organizations.id'], ),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_semantic_memories_organization_id'), 'semantic_memories', ['organization_id'], unique=False)
    op.create_index('ix_semantic_memories_scope_lookup', 'semantic_memories', ['organization_id', 'scope', 'is_active'], unique=False)
    op.create_index('ix_semantic_memories_entity', 'semantic_memories', ['entity_id'], unique=False)
    op.create_index(
        'ix_semantic_memories_embedding_hnsw', 'semantic_memories', ['embedding'], unique=False,
        postgresql_using='hnsw', postgresql_ops={'embedding': 'vector_cosine_ops'},
    )


def downgrade() -> None:
    op.drop_index('ix_semantic_memories_embedding_hnsw', table_name='semantic_memories')
    op.drop_index('ix_semantic_memories_entity', table_name='semantic_memories')
    op.drop_index('ix_semantic_memories_scope_lookup', table_name='semantic_memories')
    op.drop_index(op.f('ix_semantic_memories_organization_id'), table_name='semantic_memories')
    op.drop_table('semantic_memories')
    op.drop_index('ix_agent_messages_session_unsummarized', table_name='agent_messages')
    op.drop_table('agent_messages')
    op.drop_index(op.f('ix_agent_sessions_user_id'), table_name='agent_sessions')
    op.drop_index(op.f('ix_agent_sessions_organization_id'), table_name='agent_sessions')
    op.drop_table('agent_sessions')
    postgresql.ENUM(name='memory_entity_type').drop(op.get_bind(), checkfirst=True)
    postgresql.ENUM(name='memory_scope').drop(op.get_bind(), checkfirst=True)
    postgresql.ENUM(name='agent_message_role').drop(op.get_bind(), checkfirst=True)
    # The vector extension is left installed -- other databases objects may
    # depend on it, and dropping an extension is not this migration's call.
