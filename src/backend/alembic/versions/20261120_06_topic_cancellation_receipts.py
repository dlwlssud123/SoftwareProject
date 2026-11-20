"""Distinguish accepted proposals from cancellation receipts without proposal text."""

import sqlalchemy as sa

from alembic import op

revision = "20261120_06"
down_revision = "20261120_05"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "content_topic_requests",
        sa.Column("was_submitted", sa.Boolean(), server_default="true", nullable=False),
    )
    op.create_check_constraint(
        "ck_topic_submission_state",
        "content_topic_requests",
        "was_submitted OR status = 'withdrawn'",
    )


def downgrade() -> None:
    op.drop_constraint(
        "ck_topic_submission_state", "content_topic_requests", type_="check"
    )
    op.drop_column("content_topic_requests", "was_submitted")
