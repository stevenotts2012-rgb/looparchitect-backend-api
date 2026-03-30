"""Step D: storage + pipeline updates

Revision ID: beb724ce4e72
Revises: 006_add_bars_column
Create Date: 2026-02-25 15:52:50.636759

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'beb724ce4e72'
down_revision: Union[str, Sequence[str], None] = '006_add_bars_column'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema: add missing columns to loops table (idempotent)."""
    from sqlalchemy import inspect as sa_inspect
    conn = op.get_bind()
    inspector = sa_inspect(conn)
    existing_loop_cols = {col['name'] for col in inspector.get_columns('loops')}

    # Add columns that belong in the loops table but were absent from the
    # legacy schema created before the ORM model was updated.
    columns_to_add = [
        ('name',     sa.String(), True,  "''"),
        ('tempo',    sa.Float(),  True,  None),
        ('key',      sa.String(), True,  None),
        ('genre',    sa.String(), True,  None),
        ('file_url', sa.String(), True,  None),
    ]
    for col_name, col_type, nullable, server_default in columns_to_add:
        if col_name not in existing_loop_cols:
            op.add_column(
                'loops',
                sa.Column(
                    col_name,
                    col_type,
                    nullable=nullable,
                    server_default=sa.text(server_default) if server_default is not None else None,
                ),
            )

    # Backfill: copy title -> name for any rows that have title but no name
    op.execute("UPDATE loops SET name = title WHERE (name IS NULL OR name = '') AND title IS NOT NULL")


def downgrade() -> None:
    """Downgrade schema: remove columns added during upgrade (idempotent)."""
    from sqlalchemy import inspect as sa_inspect
    conn = op.get_bind()
    inspector = sa_inspect(conn)
    existing_loop_cols = {col['name'] for col in inspector.get_columns('loops')}

    for col_name in ('name', 'tempo', 'key', 'genre', 'file_url'):
        if col_name in existing_loop_cols:
            try:
                op.drop_column('loops', col_name)
            except Exception:
                pass
