"""Fix loops id column type for SQLite auto-increment

The previous batch_alter_table migration changed the id column type from
SERIAL (original legacy DDL) to NUMERIC.  SQLite only auto-assigns integer
row IDs when the PRIMARY KEY column is declared as INTEGER (exactly).  This
migration recreates the table with the correct INTEGER primary key so that
auto-increment works and db.refresh() succeeds after insert.

Revision ID: b2c3d4e5f6a1
Revises: a1b2c3d4e5f6
Create Date: 2026-03-30

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "b2c3d4e5f6a1"
down_revision: Union[str, Sequence[str], None] = "a1b2c3d4e5f6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Fix id column to INTEGER so SQLite auto-increment works correctly."""
    with op.batch_alter_table("loops", recreate="always") as batch_op:
        batch_op.alter_column(
            "id",
            existing_type=sa.Numeric(),
            type_=sa.Integer(),
            nullable=False,
        )


def downgrade() -> None:
    """Revert id column back to Numeric (no-op in practice)."""
    pass
