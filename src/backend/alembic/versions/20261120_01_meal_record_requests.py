"""Preserve meal calculation snapshots, edit versions and create-request receipts."""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "20261120_01"
down_revision = "20261119_01"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "meal_logs",
        sa.Column("version", sa.Integer(), server_default="1", nullable=False),
    )
    op.create_check_constraint("ck_meal_log_version", "meal_logs", "version > 0")
    op.add_column("meal_log_items", sa.Column("order_no", sa.Integer(), nullable=True))
    op.add_column(
        "meal_log_items",
        sa.Column("portion_snapshot", postgresql.JSONB(), nullable=True),
    )
    op.create_check_constraint(
        "ck_meal_item_order", "meal_log_items", "order_no IS NULL OR order_no > 0"
    )
    op.create_unique_constraint(
        "uq_meal_item_order", "meal_log_items", ["meal_log_id", "order_no"]
    )
    op.create_table(
        "meal_create_requests",
        sa.Column(
            "user_id",
            sa.Uuid(),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("key_hash", sa.String(64), primary_key=True),
        sa.Column("request_hash", sa.String(64), nullable=False),
        sa.Column(
            "meal_log_id",
            sa.Uuid(),
            sa.ForeignKey("meal_logs.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )
    op.create_index(
        "ix_meal_create_requests_meal_log_id", "meal_create_requests", ["meal_log_id"]
    )


def downgrade() -> None:
    op.drop_table("meal_create_requests")
    op.drop_constraint("uq_meal_item_order", "meal_log_items", type_="unique")
    op.drop_constraint("ck_meal_item_order", "meal_log_items", type_="check")
    op.drop_column("meal_log_items", "portion_snapshot")
    op.drop_column("meal_log_items", "order_no")
    op.drop_constraint("ck_meal_log_version", "meal_logs", type_="check")
    op.drop_column("meal_logs", "version")
