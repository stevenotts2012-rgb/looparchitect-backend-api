"""Add style fields to arrangements table (idempotent)

Revision ID: 9d1e5c8a21f0
Revises: beb724ce4e72
Create Date: 2026-03-03

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect


# revision identifiers, used by Alembic.
revision: str = "9d1e5c8a21f0"
down_revision: Union[str, Sequence[str], None] = "beb724ce4e72"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


STYLE_COLUMNS: list[tuple[str, sa.types.TypeEngine]] = [
    ("style_preset", sa.String()),
    ("style_params", sa.Text()),
    ("seed", sa.String()),
    ("structure", sa.Text()),
    ("midi_s3_key", sa.String()),
    ("stems_s3_prefix", sa.String()),
]


def _column_exists(table_name: str, column_name: str) -> bool:
    bind = op.get_bind()
    inspector = inspect(bind)
    columns = inspector.get_columns(table_name)
    return any(column.get("name") == column_name for column in columns)


def upgrade() -> None:
    """Upgrade schema."""
    for column_name, column_type in STYLE_COLUMNS:
        if not _column_exists("arrangements", column_name):
            op.add_column("arrangements", sa.Column(column_name, column_type, nullable=True))


def downgrade() -> None:
    """Downgrade schema."""
    for column_name, _ in reversed(STYLE_COLUMNS):
        if _column_exists("arrangements", column_name):
            op.drop_column("arrangements", column_name)
