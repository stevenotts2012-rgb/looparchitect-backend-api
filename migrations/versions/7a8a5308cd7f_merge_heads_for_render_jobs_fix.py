"""merge heads for render_jobs fix

Revision ID: 7a8a5308cd7f
Revises: 6b3f2a9c1d4e, a1f3c9d4e7b2
Create Date: 2026-03-26 17:59:11.867074

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '7a8a5308cd7f'
down_revision: Union[str, Sequence[str], None] = ('6b3f2a9c1d4e', 'a1f3c9d4e7b2')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    pass


def downgrade() -> None:
    """Downgrade schema."""
    pass
