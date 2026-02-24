"""Add missing loop columns

Revision ID: 001_add_missing_loop_columns
Revises: 
Create Date: 2026-02-24

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '001_add_missing_loop_columns'
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Add missing columns to loops table."""
    # Check if columns exist before adding - for idempotent upgrades
    # Add filename column
    try:
        op.add_column('loops', sa.Column('filename', sa.String(), nullable=True))
    except Exception:
        pass
    
    # Add title column
    try:
        op.add_column('loops', sa.Column('title', sa.String(), nullable=True))
    except Exception:
        pass
    
    # Add bpm column
    try:
        op.add_column('loops', sa.Column('bpm', sa.Integer(), nullable=True))
    except Exception:
        pass
    
    # Add musical_key column
    try:
        op.add_column('loops', sa.Column('musical_key', sa.String(), nullable=True))
    except Exception:
        pass
    
    # Add duration_seconds column
    try:
        op.add_column('loops', sa.Column('duration_seconds', sa.Float(), nullable=True))
    except Exception:
        pass


def downgrade() -> None:
    """Remove added columns from loops table."""
    try:
        op.drop_column('loops', 'duration_seconds')
    except Exception:
        pass
    
    try:
        op.drop_column('loops', 'musical_key')
    except Exception:
        pass
    
    try:
        op.drop_column('loops', 'bpm')
    except Exception:
        pass
    
    try:
        op.drop_column('loops', 'title')
    except Exception:
        pass
    
    try:
        op.drop_column('loops', 'filename')
    except Exception:
        pass
