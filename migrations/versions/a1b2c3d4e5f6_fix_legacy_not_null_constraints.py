"""Fix legacy NOT NULL constraints on loops table

The original loops table was created with NOT NULL constraints on legacy
columns (title, artist_name, duration_seconds, file_path) that no longer
match the current ORM model.  This migration relaxes those constraints so
that new rows created via the current API can be inserted successfully.

Revision ID: a1b2c3d4e5f6
Revises: 6b3f2a9c1d4e
Create Date: 2026-03-30

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "a1b2c3d4e5f6"
down_revision: Union[str, Sequence[str], None] = "6b3f2a9c1d4e"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Make legacy NOT NULL columns nullable using batch_alter_table (SQLite-safe)."""
    with op.batch_alter_table("loops", recreate="auto") as batch_op:
        batch_op.alter_column("title", existing_type=sa.String(), nullable=True)
        batch_op.alter_column("artist_name", existing_type=sa.String(), nullable=True)
        batch_op.alter_column("duration_seconds", existing_type=sa.Float(), nullable=True)
        batch_op.alter_column("file_path", existing_type=sa.String(), nullable=True)


def downgrade() -> None:
    """Restore NOT NULL constraints (best-effort; may fail if NULL rows exist)."""
    with op.batch_alter_table("loops", recreate="auto") as batch_op:
        batch_op.alter_column("file_path", existing_type=sa.String(), nullable=False)
        batch_op.alter_column("duration_seconds", existing_type=sa.Float(), nullable=False)
        batch_op.alter_column("artist_name", existing_type=sa.String(), nullable=False)
        batch_op.alter_column("title", existing_type=sa.String(), nullable=False)
