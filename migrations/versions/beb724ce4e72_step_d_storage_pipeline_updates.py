"""Step D: storage + pipeline updates

Revision ID: beb724ce4e72
Revises: 006_add_bars_column
Create Date: 2026-02-25 15:52:50.636759

NOTE: The drops in this migration are intentionally guarded with existence
checks.  If the tables were already removed (e.g. by a manual cleanup or a
previous partial run) the migration is still applied successfully and the
``alembic_version`` row is recorded.  Subsequent migrations that add columns
to ``arrangements`` rely on the table having been re-created by either this
migration's downgrade path or by SQLAlchemy ``create_all()``; in a fully
Alembic-managed schema those tables would be created by a dedicated migration
step added after this one.
"""
from typing import Sequence, Union

import logging

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect

logger = logging.getLogger(__name__)


# revision identifiers, used by Alembic.
revision: str = 'beb724ce4e72'
down_revision: Union[str, Sequence[str], None] = '006_add_bars_column'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema (drops guarded by existence checks to be safe)."""
    conn = op.get_bind()
    inspector = inspect(conn)
    existing_tables = set(inspector.get_table_names())

    if 'loops' in existing_tables:
        try:
            op.drop_index(op.f('ix_loops_id'), table_name='loops')
        except Exception as exc:
            logger.warning("Could not drop index ix_loops_id (may not exist): %s", exc)
        op.drop_table('loops')

    if 'arrangements' in existing_tables:
        for idx_name in ('idx_arrangement_loop_status', 'ix_arrangements_id', 'ix_arrangements_loop_id'):
            try:
                op.drop_index(op.f(idx_name), table_name='arrangements')
            except Exception as exc:
                logger.warning("Could not drop index %s (may not exist): %s", idx_name, exc)
        op.drop_table('arrangements')


def downgrade() -> None:
    """Downgrade schema (recreates tables dropped in upgrade).

    WARNING: This downgrade path is intentionally destructive.  Running
    ``alembic downgrade`` past this revision on a production database will
    **permanently drop** the ``loops`` and ``arrangements`` tables and any
    data they contain.  Only run this in a controlled environment with a
    verified backup.

    The table/index creation steps are guarded so that a partial re-run
    (e.g. after a failed attempt) does not crash on pre-existing objects.
    """
    conn = op.get_bind()
    inspector = inspect(conn)
    existing_tables = set(inspector.get_table_names())

    if 'arrangements' not in existing_tables:
        op.create_table('arrangements',
        sa.Column('id', sa.INTEGER(), nullable=False),
        sa.Column('loop_id', sa.INTEGER(), nullable=False),
        sa.Column('status', sa.VARCHAR(), server_default=sa.text("'queued'"), nullable=False),
        sa.Column('target_seconds', sa.INTEGER(), nullable=False),
        sa.Column('genre', sa.VARCHAR(), nullable=True),
        sa.Column('intensity', sa.VARCHAR(), nullable=True),
        sa.Column('include_stems', sa.BOOLEAN(), server_default=sa.text("'0'"), nullable=False),
        sa.Column('output_file_url', sa.VARCHAR(), nullable=True),
        sa.Column('stems_zip_url', sa.VARCHAR(), nullable=True),
        sa.Column('arrangement_json', sa.TEXT(), nullable=True),
        sa.Column('error_message', sa.TEXT(), nullable=True),
        sa.Column('created_at', sa.DATETIME(), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=False),
        sa.Column('updated_at', sa.DATETIME(), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=False),
        sa.Column('output_s3_key', sa.VARCHAR(), nullable=True),
        sa.Column('output_url', sa.VARCHAR(), nullable=True),
        sa.ForeignKeyConstraint(['loop_id'], ['loops.id'], ),
        sa.PrimaryKeyConstraint('id')
        )

    for idx_name, cols in [
        ('ix_arrangements_loop_id', ['loop_id']),
        ('ix_arrangements_id', ['id']),
        # Note: 'idx_arrangement_loop_status' is a legacy name that pre-dates
        # the ix_ convention; it is intentionally preserved as-is to match
        # the index name that existed on production databases.
        ('idx_arrangement_loop_status', ['loop_id', 'status']),
    ]:
        try:
            op.create_index(op.f(idx_name), 'arrangements', cols, unique=False)
        except (sa.exc.OperationalError, sa.exc.ProgrammingError) as exc:
            logger.warning("Could not create index %s (may already exist): %s", idx_name, exc)

    if 'loops' not in existing_tables:
        op.create_table('loops',
        sa.Column('id', sa.INTEGER(), nullable=False),
        sa.Column('name', sa.VARCHAR(), nullable=False),
        sa.Column('tempo', sa.FLOAT(), nullable=True),
        sa.Column('key', sa.VARCHAR(), nullable=True),
        sa.Column('genre', sa.VARCHAR(), nullable=True),
        sa.Column('file_url', sa.VARCHAR(), nullable=True),
        sa.Column('created_at', sa.DATETIME(), nullable=True),
        sa.Column('bpm', sa.INTEGER(), server_default=sa.text('(NULL)'), nullable=True),
        sa.Column('duration_seconds', sa.FLOAT(), server_default=sa.text('(NULL)'), nullable=True),
        sa.Column('filename', sa.VARCHAR(), server_default=sa.text('(NULL)'), nullable=True),
        sa.Column('musical_key', sa.VARCHAR(), server_default=sa.text('(NULL)'), nullable=True),
        sa.Column('title', sa.VARCHAR(), server_default=sa.text('(NULL)'), nullable=True),
        sa.Column('status', sa.VARCHAR(), nullable=True),
        sa.Column('processed_file_url', sa.VARCHAR(), nullable=True),
        sa.Column('analysis_json', sa.TEXT(), nullable=True),
        sa.Column('file_key', sa.VARCHAR(), nullable=True),
        sa.Column('bars', sa.INTEGER(), nullable=True),
        sa.PrimaryKeyConstraint('id')
        )

    try:
        op.create_index(op.f('ix_loops_id'), 'loops', ['id'], unique=False)
    except (sa.exc.OperationalError, sa.exc.ProgrammingError) as exc:
        logger.warning("Could not create index ix_loops_id (may already exist): %s", exc)
