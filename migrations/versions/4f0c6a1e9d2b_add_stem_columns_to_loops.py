"""Add stem metadata columns to loops table (idempotent)

Revision ID: 4f0c6a1e9d2b
Revises: 008_add_style_profile_to_arrangements
Create Date: 2026-03-12

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect


# revision identifiers, used by Alembic.
revision: str = "4f0c6a1e9d2b"
down_revision: Union[str, Sequence[str], None] = "008_add_style_profile_to_arrangements"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


STEM_COLUMNS: list[tuple[str, sa.types.TypeEngine, bool, str | None]] = [
    ("is_stem_pack", sa.String(), True, "false"),
    ("stem_roles_json", sa.Text(), True, None),
    ("stem_files_json", sa.Text(), True, None),
    ("stem_validation_json", sa.Text(), True, None),
]


def _column_exists(table_name: str, column_name: str) -> bool:
    bind = op.get_bind()
    inspector = inspect(bind)
    columns = inspector.get_columns(table_name)
    return any(column.get("name") == column_name for column in columns)


def upgrade() -> None:
    """Upgrade schema."""
    for column_name, column_type, nullable, server_default in STEM_COLUMNS:
        if not _column_exists("loops", column_name):
            op.add_column(
                "loops",
                sa.Column(
                    column_name,
                    column_type,
                    nullable=nullable,
                    server_default=sa.text(f"'{server_default}'") if server_default is not None else None,
                ),
            )


def downgrade() -> None:
    """Downgrade schema."""
    for column_name, _, _, _ in reversed(STEM_COLUMNS):
        if _column_exists("loops", column_name):
            op.drop_column("loops", column_name)
