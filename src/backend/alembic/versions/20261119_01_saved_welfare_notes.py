"""Add private progress notes to saved welfare services."""

import sqlalchemy as sa

from alembic import op

revision = "20261119_01"
down_revision = "20261118_01"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "saved_welfare_services",
        sa.Column("progress_note", sa.String(length=2000), nullable=True),
    )
    op.add_column(
        "saved_welfare_services",
        sa.Column("note_updated_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("saved_welfare_services", "note_updated_at")
    op.drop_column("saved_welfare_services", "progress_note")
