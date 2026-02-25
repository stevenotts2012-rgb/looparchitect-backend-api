"""Add S3 output fields to arrangements

Revision ID: 005_add_arrangement_s3_fields
Revises: 004_add_file_key
Create Date: 2026-02-25

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '005_add_arrangement_s3_fields'
down_revision = '004_add_file_key'
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Add S3 output fields to arrangements table."""
    try:
        op.add_column('arrangements', sa.Column('output_s3_key', sa.String(), nullable=True))
    except Exception:
        pass

    try:
        op.add_column('arrangements', sa.Column('output_url', sa.String(), nullable=True))
    except Exception:
        pass


def downgrade() -> None:
    """Remove S3 output fields from arrangements table."""
    try:
        op.drop_column('arrangements', 'output_url')
    except Exception:
        pass

    try:
        op.drop_column('arrangements', 'output_s3_key')
    except Exception:
        pass
