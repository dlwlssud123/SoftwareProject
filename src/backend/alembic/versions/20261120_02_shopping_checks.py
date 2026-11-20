"""Store purchase checks separately from derived planned ingredients."""

import sqlalchemy as sa

from alembic import op

revision = "20261120_02"
down_revision = "20261120_01"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "shopping_checks",
        sa.Column(
            "user_id",
            sa.Uuid(),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("plan_date", sa.Date(), primary_key=True),
        sa.Column("item_key", sa.String(64), primary_key=True),
        sa.Column("source_hash", sa.String(64), nullable=False),
        sa.Column("checked", sa.Boolean(), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("shopping_checks")
