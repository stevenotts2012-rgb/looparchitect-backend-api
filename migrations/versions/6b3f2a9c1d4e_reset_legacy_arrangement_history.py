"""Reset legacy arrangement history to unsaved state

Revision ID: 6b3f2a9c1d4e
Revises: 4f0c6a1e9d2b
Create Date: 2026-03-16

This one-time migration clears pre-existing history visibility so only
arrangements explicitly saved after rollout are shown in default history.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect


# revision identifiers, used by Alembic.
revision: str = "6b3f2a9c1d4e"
down_revision: Union[str, Sequence[str], None] = "4f0c6a1e9d2b"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _column_exists(table_name: str, column_name: str) -> bool:
    bind = op.get_bind()
    inspector = inspect(bind)
    columns = inspector.get_columns(table_name)
    return any(column.get("name") == column_name for column in columns)


def upgrade() -> None:
    """Upgrade schema and reset legacy saved history rows."""
    if not _column_exists("arrangements", "is_saved"):
        op.add_column(
            "arrangements",
            sa.Column("is_saved", sa.Boolean(), nullable=True, server_default=sa.text("false")),
        )

    if not _column_exists("arrangements", "saved_at"):
        op.add_column("arrangements", sa.Column("saved_at", sa.DateTime(), nullable=True))

    # One-time cleanup: hide all pre-existing history entries.
    # After this migration, only explicit save actions will repopulate history.
    op.execute(
        sa.text(
            """
            UPDATE arrangements
            SET is_saved = false,
                saved_at = NULL
            WHERE created_at IS NULL OR created_at <= CURRENT_TIMESTAMP
            """
        )
    )


def downgrade() -> None:
    """Downgrade schema."""
    # Data reset is intentionally not reversed.
    pass
