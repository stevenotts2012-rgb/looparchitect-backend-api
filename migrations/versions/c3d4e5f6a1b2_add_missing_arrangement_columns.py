"""Add missing producer/stem columns to arrangements table

Revision ID: c3d4e5f6a1b2
Revises: b2c3d4e5f6a1
Create Date: 2026-03-30

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect


# revision identifiers, used by Alembic.
revision: str = "c3d4e5f6a1b2"
down_revision: Union[str, Sequence[str], None] = "b2c3d4e5f6a1"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _column_exists(table_name: str, column_name: str) -> bool:
    bind = op.get_bind()
    inspector = inspect(bind)
    columns = inspector.get_columns(table_name)
    return any(column.get("name") == column_name for column in columns)


def upgrade() -> None:
    """Add producer/stem-engine columns that are present in the ORM model
    but were never added by previous migrations."""
    columns_to_add = [
        ("producer_arrangement_json", sa.Text(), True, None),
        ("render_plan_json",          sa.Text(), True, None),
        ("stem_arrangement_json",     sa.Text(), True, None),
        ("stem_render_path",          sa.String(), True, None),
        ("rendered_from_stems",       sa.Boolean(), True, "false"),
    ]
    for col_name, col_type, nullable, server_default in columns_to_add:
        if not _column_exists("arrangements", col_name):
            op.add_column(
                "arrangements",
                sa.Column(
                    col_name,
                    col_type,
                    nullable=nullable,
                    server_default=sa.text(server_default) if server_default is not None else None,
                ),
            )


def downgrade() -> None:
    """Remove the columns added during upgrade."""
    for col_name in (
        "rendered_from_stems",
        "stem_render_path",
        "stem_arrangement_json",
        "render_plan_json",
        "producer_arrangement_json",
    ):
        if _column_exists("arrangements", col_name):
            try:
                op.drop_column("arrangements", col_name)
            except Exception:
                pass
