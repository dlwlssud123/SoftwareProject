"""Store meal recommendation results and the published recipe revisions used."""

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

from alembic import op

revision = "20261115_01"
down_revision = "20261114_03"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "recommendation_runs",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "user_id",
            sa.Uuid(),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("meal_time", sa.String(16), nullable=False),
        sa.Column("rules_version", sa.String(64), nullable=False),
        sa.Column("evaluated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index(
        "ix_recommendation_runs_user_evaluated",
        "recommendation_runs",
        ["user_id", "evaluated_at"],
    )
    op.create_table(
        "recommendation_items",
        sa.Column(
            "run_id",
            sa.Uuid(),
            sa.ForeignKey("recommendation_runs.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("rank", sa.Integer(), primary_key=True),
        sa.Column(
            "recipe_revision_id",
            sa.Uuid(),
            sa.ForeignKey("recipe_revisions.id"),
            nullable=False,
        ),
        sa.Column("reasons", JSONB(), nullable=False),
        sa.Column("seasonal_ingredients", JSONB(), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("recommendation_items")
    op.drop_table("recommendation_runs")
