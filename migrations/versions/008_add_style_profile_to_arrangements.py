"""Add style profile JSON column to arrangements

Revision ID: 008_add_style_profile_to_arrangements
Revises: 007_add_progress_to_arrangements
Create Date: 2026-03-03

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '008_add_style_profile_to_arrangements'
down_revision = '007_add_progress_to_arrangements'
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Add style profile columns to arrangements table for LLM V2 support."""
    try:
        op.add_column(
            'arrangements',
            sa.Column('style_profile_json', sa.Text(), nullable=True)
        )
    except Exception:
        pass

    try:
        op.add_column(
            'arrangements',
            sa.Column('ai_parsing_used', sa.Boolean(), nullable=True, server_default='0')
        )
    except Exception:
        pass


def downgrade() -> None:
    """Remove style profile columns from arrangements table."""
    try:
        op.drop_column('arrangements', 'ai_parsing_used')
    except Exception:
        pass

    try:
        op.drop_column('arrangements', 'style_profile_json')
    except Exception:
        pass
