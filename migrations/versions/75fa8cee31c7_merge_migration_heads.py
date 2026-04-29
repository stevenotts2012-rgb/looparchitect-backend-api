"""merge migration heads

Revision ID: 75fa8cee31c7
Revises: 302bd7818e5b, c1d2e3f4a5b6
Create Date: 2026-04-29 06:10:05.838317

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '75fa8cee31c7'
down_revision: Union[str, Sequence[str], None] = ('302bd7818e5b', 'c1d2e3f4a5b6')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    pass


def downgrade() -> None:
    """Downgrade schema."""
    pass
