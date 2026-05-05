"""Add producer persistence fields to arrangements table

Adds columns for recording the generative producer system's decisions:
- producer_plan_json : full ProducerPlan as JSON
- decision_log_json  : JSON array of per-event producer decisions
- section_summary_json: JSON array of per-section summaries
- quality_score      : 0–1 arrangement quality score

Revision ID: d2e3f4a5b6c7
Revises: 75fa8cee31c7
Branch Labels: None
Depends On: None
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "d2e3f4a5b6c7"
down_revision: Union[str, Sequence[str], None] = "75fa8cee31c7"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "arrangements",
        sa.Column("producer_plan_json", sa.Text(), nullable=True),
    )
    op.add_column(
        "arrangements",
        sa.Column("decision_log_json", sa.Text(), nullable=True),
    )
    op.add_column(
        "arrangements",
        sa.Column("section_summary_json", sa.Text(), nullable=True),
    )
    op.add_column(
        "arrangements",
        sa.Column("quality_score", sa.Float(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("arrangements", "quality_score")
    op.drop_column("arrangements", "section_summary_json")
    op.drop_column("arrangements", "decision_log_json")
    op.drop_column("arrangements", "producer_plan_json")
