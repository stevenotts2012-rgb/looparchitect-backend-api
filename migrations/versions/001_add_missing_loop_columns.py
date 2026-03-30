"""Add missing loop columns

Revision ID: 001_add_missing_loop_columns
Revises: 
Create Date: 2026-02-24

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect

# revision identifiers, used by Alembic.
revision = '001_add_missing_loop_columns'
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Add missing columns to loops table (idempotent)."""
    conn = op.get_bind()
    inspector = inspect(conn)

    # Skip entirely if the table doesn't exist yet (fresh DB managed by init_db)
    if 'loops' not in inspector.get_table_names():
        return

    existing_columns = {col['name'] for col in inspector.get_columns('loops')}
    
    # Add columns only if they don't exist
    if 'filename' not in existing_columns:
        op.add_column('loops', sa.Column('filename', sa.String(), nullable=True))
    
    if 'title' not in existing_columns:
        op.add_column('loops', sa.Column('title', sa.String(), nullable=True))
    
    if 'bpm' not in existing_columns:
        op.add_column('loops', sa.Column('bpm', sa.Integer(), nullable=True))
    
    if 'musical_key' not in existing_columns:
        op.add_column('loops', sa.Column('musical_key', sa.String(), nullable=True))
    
    if 'duration_seconds' not in existing_columns:
        op.add_column('loops', sa.Column('duration_seconds', sa.Float(), nullable=True))
     
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
