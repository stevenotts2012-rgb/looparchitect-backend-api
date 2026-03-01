"""fix render jobs progress type

Revision ID: 7c05015ca255  
Revises: 80dcd1ed7522  
Create Date: 2026-03-01 14:41:46.410778  

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '7c05015ca255'
down_revision: Union[str, Sequence[str], None] = '80dcd1ed7522'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Change progress column from Integer to Float for percentage precision."""
    # SQLite doesn't support ALTER COLUMN directly, so use batch mode
    with op.batch_alter_table('render_jobs') as batch_op:
        batch_op.alter_column('progress',
                              type_=sa.Float(),
                              existing_type=sa.Integer(),
                              existing_nullable=False,
                              existing_server_default='0')


def downgrade() -> None:
    """Revert progress column back to Integer."""
    with op.batch_alter_table('render_jobs') as batch_op:
        batch_op.alter_column('progress',
                              type_=sa.Integer(),
                              existing_type=sa.Float(),
                              existing_nullable=False,
                              existing_server_default='0')
