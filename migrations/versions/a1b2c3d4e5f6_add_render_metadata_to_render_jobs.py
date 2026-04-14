"""Add render_metadata_json to render_jobs

Phase 3 render observability: persists execution truth data on every render job.

Revision ID: a1b2c3d4e5f6
Revises: 80dcd1ed7522
Create Date: 2026-04-14 12:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'a1b2c3d4e5f6'
down_revision: Union[str, Sequence[str], None] = '80dcd1ed7522'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Add render_metadata_json column to render_jobs table.

    This column stores Phase 3 observability metadata as a JSON blob.
    It is nullable and additive — existing rows simply have NULL.
    """
    op.add_column(
        'render_jobs',
        sa.Column('render_metadata_json', sa.Text(), nullable=True),
    )


def downgrade() -> None:
    """Remove render_metadata_json column from render_jobs table."""
    op.drop_column('render_jobs', 'render_metadata_json')
