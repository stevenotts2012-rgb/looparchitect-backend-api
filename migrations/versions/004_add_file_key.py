"""Add file_key column for S3 storage

Revision ID: 004_add_file_key
Revises: 003_add_task_fields
Create Date: 2026-02-25

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '004_add_file_key'
down_revision = '003_add_task_fields'
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Add file_key column to loops table for S3 key storage."""
    # Add file_key column - stores S3 key like "uploads/uuid.wav"
    try:
        op.add_column('loops', sa.Column('file_key', sa.String(), nullable=True))
    except Exception:
        # Column might already exist
        pass


def downgrade() -> None:
    """Remove file_key column."""
    try:
        op.drop_column('loops', 'file_key')
    except Exception:
        pass
