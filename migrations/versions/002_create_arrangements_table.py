"""Add arrangements table for audio generation workflow

Revision ID: 002_create_arrangements_table
Revises: 001_add_missing_loop_columns
Create Date: 2026-02-24

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '002_create_arrangements_table'
down_revision = '001_add_missing_loop_columns'
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Create arrangements table."""
    op.create_table(
        'arrangements',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('loop_id', sa.Integer(), nullable=False),
        sa.Column('status', sa.String(), nullable=False, server_default='queued'),
        sa.Column('target_seconds', sa.Integer(), nullable=False),
        sa.Column('genre', sa.String(), nullable=True),
        sa.Column('intensity', sa.String(), nullable=True),
        sa.Column('include_stems', sa.Boolean(), nullable=False, server_default='0'),
        sa.Column('output_file_url', sa.String(), nullable=True),
        sa.Column('stems_zip_url', sa.String(), nullable=True),
        sa.Column('arrangement_json', sa.Text(), nullable=True),
        sa.Column('error_message', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(['loop_id'], ['loops.id'], ),
        sa.PrimaryKeyConstraint('id')
    )
    
    # Create indexes
    op.create_index('ix_arrangements_id', 'arrangements', ['id'], unique=False)
    op.create_index('ix_arrangements_loop_id', 'arrangements', ['loop_id'], unique=False)
    op.create_index('idx_arrangement_loop_status', 'arrangements', ['loop_id', 'status'], unique=False)


def downgrade() -> None:
    """Drop arrangements table."""
    op.drop_index('idx_arrangement_loop_status', table_name='arrangements')
    op.drop_index('ix_arrangements_loop_id', table_name='arrangements')
    op.drop_index('ix_arrangements_id', table_name='arrangements')
    op.drop_table('arrangements')
