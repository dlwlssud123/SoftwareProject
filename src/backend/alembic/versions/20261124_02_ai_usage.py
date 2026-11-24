"""Daily bounded AI usage without storing user prompts or media."""

import sqlalchemy as sa

from alembic import op

revision = "20261124_02"
down_revision = "20261124_01"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "ai_usage_buckets",
        sa.Column("bucket_id", sa.String(80), primary_key=True),
        sa.Column("usage_date", sa.Date(), primary_key=True),
        sa.Column("calls", sa.Integer(), nullable=False),
        sa.CheckConstraint("calls > 0", name="ck_ai_usage_positive"),
    )


def downgrade() -> None:
    op.drop_table("ai_usage_buckets")
