"""Add arrangement_id to render_jobs

Links each completed render job to the Arrangement record it produced or
updated, so that GET /api/v1/jobs/{job_id} can surface arrangement_id directly.

Revision ID: c1d2e3f4a5b6
Revises: a1b2c3d4e5f6
Branch Labels: None
Depends On: None
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "c1d2e3f4a5b6"
down_revision: Union[str, Sequence[str], None] = "a1b2c3d4e5f6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "render_jobs",
        sa.Column(
            "arrangement_id",
            sa.Integer(),
            sa.ForeignKey("arrangements.id"),
            nullable=True,
        ),
    )
    op.create_index(
        "ix_render_jobs_arrangement_id",
        "render_jobs",
        ["arrangement_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_render_jobs_arrangement_id", table_name="render_jobs")
    op.drop_column("render_jobs", "arrangement_id")
