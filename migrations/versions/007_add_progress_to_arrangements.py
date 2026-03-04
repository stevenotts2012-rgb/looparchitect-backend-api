"""Add progress tracking to arrangements

Revision ID: 007_add_progress_to_arrangements
Revises: 7c05015ca255, 9d1e5c8a21f0
Create Date: 2026-02-25

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '007_add_progress_to_arrangements'
down_revision = ('7c05015ca255', '9d1e5c8a21f0')
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Add progress tracking columns to arrangements table."""
    try:
        op.add_column('arrangements', sa.Column('progress', sa.Float(), nullable=True, server_default='0.0'))
    except Exception:
        pass

    try:
        op.add_column('arrangements', sa.Column('progress_message', sa.String(256), nullable=True))
    except Exception:
        pass


def downgrade() -> None:
    """Remove progress tracking columns from arrangements table."""
    try:
        op.drop_column('arrangements', 'progress_message')
    except Exception:
        pass

    try:
        op.drop_column('arrangements', 'progress')
    except Exception:
        pass
