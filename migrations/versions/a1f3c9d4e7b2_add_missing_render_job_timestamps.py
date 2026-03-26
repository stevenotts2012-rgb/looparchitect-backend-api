"""add missing render job timestamps

Revision ID: a1f3c9d4e7b2
Revises: 7c05015ca255
Create Date: 2026-03-26 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "a1f3c9d4e7b2"
down_revision: Union[str, Sequence[str], None] = "7c05015ca255"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Add missing render_jobs timestamp columns if absent (SQLite-safe, idempotent)."""
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    table_names = inspector.get_table_names()

    if "render_jobs" not in table_names:
        return

    existing_columns = {col["name"] for col in inspector.get_columns("render_jobs")}

    columns_to_add = [
        ("queued_at", sa.DateTime(), True),
        ("started_at", sa.DateTime(), True),
        ("finished_at", sa.DateTime(), True),
        ("expires_at", sa.DateTime(), True),
    ]

    for name, column_type, nullable in columns_to_add:
        if name not in existing_columns:
            op.add_column(
                "render_jobs",
                sa.Column(name, column_type, nullable=nullable),
            )


def downgrade() -> None:
    """Drop added render_jobs timestamp columns if present (SQLite-safe, idempotent)."""
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    table_names = inspector.get_table_names()

    if "render_jobs" not in table_names:
        return

    existing_columns = {col["name"] for col in inspector.get_columns("render_jobs")}

    for name in ("expires_at", "finished_at", "started_at", "queued_at"):
        if name in existing_columns:
            op.drop_column("render_jobs", name)
