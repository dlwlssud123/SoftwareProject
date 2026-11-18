"""Store Kakao identities without provider credentials."""

import sqlalchemy as sa

from alembic import op

revision = "20261118_01"
down_revision = "20261117_02"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "kakao_identities",
        sa.Column("app_id", sa.BigInteger(), nullable=False),
        sa.Column("subject", sa.BigInteger(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.PrimaryKeyConstraint("app_id", "subject"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.UniqueConstraint("user_id"),
    )


def downgrade() -> None:
    op.drop_table("kakao_identities")
