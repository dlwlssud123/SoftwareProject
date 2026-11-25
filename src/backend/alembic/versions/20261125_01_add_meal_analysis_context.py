"""Keep confirmed exclusions without reconstructing historical evidence."""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "20261125_01"
down_revision = "20261124_02"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "meal_logs", sa.Column("analysis_context", postgresql.JSONB(), nullable=True)
    )
    op.add_column(
        "meal_log_items", sa.Column("origin", postgresql.JSONB(), nullable=True)
    )


def downgrade():
    op.drop_column("meal_log_items", "origin")
    op.drop_column("meal_logs", "analysis_context")
