"""Merge render_metadata and reset_history heads into a single head.

Two independent branches developed in parallel:
  - a1b2c3d4e5f6: Phase 3 render observability (adds render_metadata_json to render_jobs)
  - 6b3f2a9c1d4e: Reset legacy arrangement history visibility

This empty merge revision unifies them so that `alembic upgrade head` has
exactly one target and the Railway release phase (`alembic upgrade head`)
succeeds deterministically.

Revision ID: 302bd7818e5b
Revises: 6b3f2a9c1d4e, a1b2c3d4e5f6
Create Date: 2026-04-14 17:58:32.209013

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '302bd7818e5b'
down_revision: Union[str, Sequence[str], None] = ('6b3f2a9c1d4e', 'a1b2c3d4e5f6')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    pass


def downgrade() -> None:
    """Downgrade schema."""
    pass
