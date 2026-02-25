"""Add bars column to loops table

Revision ID: 006_add_bars_column
Revises: 005_add_arrangement_s3_fields
Create Date: 2026-02-25

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '006_add_bars_column'
down_revision = '005_add_arrangement_s3_fields'
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Add bars column to loops table."""
    try:
        op.add_column('loops', sa.Column('bars', sa.Integer(), nullable=True))
    except Exception:
        # Column might already exist
        pass


def downgrade() -> None:
    """Remove bars column."""
    try:
        op.drop_column('loops', 'bars')
    except Exception:
        pass
