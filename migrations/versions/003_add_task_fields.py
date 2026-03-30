"""Add background task fields to loops table

Revision ID: 003_add_task_fields
Revises: 002_create_arrangements_table
Create Date: 2026-02-24

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect


# revision identifiers, used by Alembic.
revision = '003_add_task_fields'
down_revision = '002_create_arrangements_table'
branch_labels = None
depends_on = None


def upgrade():
    """Add status, processed_file_url, and analysis_json columns to loops table."""
    conn = op.get_bind()
    inspector = inspect(conn)
    existing_columns = {col['name'] for col in inspector.get_columns('loops')}

    # Add status column only if it doesn't already exist
    if 'status' not in existing_columns:
        op.add_column('loops', sa.Column('status', sa.String(), nullable=True))

    # Add processed_file_url column
    if 'processed_file_url' not in existing_columns:
        op.add_column('loops', sa.Column('processed_file_url', sa.String(), nullable=True))

    # Add analysis_json column
    if 'analysis_json' not in existing_columns:
        op.add_column('loops', sa.Column('analysis_json', sa.Text(), nullable=True))

    # Update existing rows to have 'pending' status
    op.execute("UPDATE loops SET status = 'pending' WHERE status IS NULL")


def downgrade():
    """Remove background task fields from loops table."""
    op.drop_column('loops', 'analysis_json')
    op.drop_column('loops', 'processed_file_url')
    op.drop_column('loops', 'status')
