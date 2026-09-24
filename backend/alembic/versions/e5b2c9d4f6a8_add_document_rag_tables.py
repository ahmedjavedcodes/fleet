"""add_document_rag_tables

Revision ID: e5b2c9d4f6a8
Revises: d3e8f5a1b7c2
Create Date: 2026-09-24 18:00:00.000000

Hybrid document RAG (hybrid-document-rag-pipeline.md): documents are the
system of record (and the ingestion lease), chunks hold the text Pinecone
vectors point at, ingest failures are the summarization dead-letter log.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = 'e5b2c9d4f6a8'
down_revision: Union[str, None] = 'd3e8f5a1b7c2'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    document_type = postgresql.ENUM('manual', 'policy', 'supplier_invoice', 'incident_report', 'legal', name='document_type')
    document_status = postgresql.ENUM('processing', 'ready', 'failed', name='document_status')

    op.create_table('documents',
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('filename', sa.String(length=255), nullable=False),
    sa.Column('document_type', document_type, nullable=False),
    sa.Column('vehicle_id', sa.UUID(), nullable=True),
    sa.Column('status', document_status, nullable=False),
    sa.Column('version', sa.Integer(), nullable=False),
    sa.Column('content_sha256', sa.String(length=64), nullable=False),
    sa.Column('size_bytes', sa.Integer(), nullable=False),
    sa.Column('chunk_count', sa.Integer(), server_default='0', nullable=False),
    sa.Column('tables_found', sa.Integer(), server_default='0', nullable=False),
    sa.Column('tables_summarized', sa.Integer(), server_default='0', nullable=False),
    sa.Column('error_message', sa.Text(), nullable=True),
    sa.Column('processing_started_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('uploaded_by', sa.UUID(), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('organization_id', sa.UUID(), nullable=False),
    sa.ForeignKeyConstraint(['organization_id'], ['organizations.id'], ),
    sa.ForeignKeyConstraint(['uploaded_by'], ['users.id'], ),
    sa.ForeignKeyConstraint(['vehicle_id'], ['vehicles.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_documents_organization_id'), 'documents', ['organization_id'], unique=False)
    op.create_index('ix_documents_org_type_status', 'documents', ['organization_id', 'document_type', 'status'], unique=False)

    op.create_table('document_chunks',
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('document_id', sa.UUID(), nullable=False),
    sa.Column('chunk_index', sa.Integer(), nullable=False),
    sa.Column('text', sa.Text(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('organization_id', sa.UUID(), nullable=False),
    sa.ForeignKeyConstraint(['document_id'], ['documents.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['organization_id'], ['organizations.id'], ),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('document_id', 'chunk_index', name='uq_document_chunks_doc_index')
    )
    op.create_index(op.f('ix_document_chunks_document_id'), 'document_chunks', ['document_id'], unique=False)
    op.create_index(op.f('ix_document_chunks_organization_id'), 'document_chunks', ['organization_id'], unique=False)

    op.create_table('document_ingest_failures',
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('document_id', sa.UUID(), nullable=False),
    sa.Column('stage', sa.String(length=50), nullable=False),
    sa.Column('error_message', sa.Text(), nullable=False),
    sa.Column('payload', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('organization_id', sa.UUID(), nullable=False),
    sa.ForeignKeyConstraint(['document_id'], ['documents.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['organization_id'], ['organizations.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_document_ingest_failures_document_id'), 'document_ingest_failures', ['document_id'], unique=False)
    op.create_index(op.f('ix_document_ingest_failures_organization_id'), 'document_ingest_failures', ['organization_id'], unique=False)


def downgrade() -> None:
    op.drop_index(op.f('ix_document_ingest_failures_organization_id'), table_name='document_ingest_failures')
    op.drop_index(op.f('ix_document_ingest_failures_document_id'), table_name='document_ingest_failures')
    op.drop_table('document_ingest_failures')
    op.drop_index(op.f('ix_document_chunks_organization_id'), table_name='document_chunks')
    op.drop_index(op.f('ix_document_chunks_document_id'), table_name='document_chunks')
    op.drop_table('document_chunks')
    op.drop_index('ix_documents_org_type_status', table_name='documents')
    op.drop_index(op.f('ix_documents_organization_id'), table_name='documents')
    op.drop_table('documents')
    postgresql.ENUM(name='document_status').drop(op.get_bind(), checkfirst=True)
    postgresql.ENUM(name='document_type').drop(op.get_bind(), checkfirst=True)
