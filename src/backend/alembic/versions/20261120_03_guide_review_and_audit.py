"""Add guide review state, optimistic versions and metadata-only audit events."""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "20261120_03"
down_revision = "20261120_02"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "life_guides",
        sa.Column("version", sa.Integer(), server_default="1", nullable=False),
    )
    op.add_column(
        "life_guides",
        sa.Column(
            "review_status", sa.String(16), server_default="draft", nullable=False
        ),
    )
    op.add_column("life_guides", sa.Column("review_note", sa.Text(), nullable=True))
    op.add_column("life_guides", sa.Column("reviewed_by", sa.Uuid(), nullable=True))
    op.add_column(
        "life_guides",
        sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "life_guides",
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )
    # Preserve public visibility without inventing a reviewer or a review timestamp.
    op.execute("UPDATE life_guides SET review_status = 'approved' WHERE is_published")
    op.create_foreign_key(
        "fk_life_guide_reviewer",
        "life_guides",
        "users",
        ["reviewed_by"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_check_constraint("ck_life_guide_version", "life_guides", "version > 0")
    op.create_check_constraint(
        "ck_life_guide_review_status",
        "life_guides",
        "review_status IN ('draft', 'review', 'approved', 'rejected')",
    )
    op.create_check_constraint(
        "ck_life_guide_published_review",
        "life_guides",
        "NOT is_published OR review_status = 'approved'",
    )
    op.create_table(
        "guide_audit_events",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("guide_id", sa.Uuid(), nullable=False),
        sa.Column("actor_id", sa.Uuid(), nullable=True),
        sa.Column("action", sa.String(16), nullable=False),
        sa.Column("before_state", postgresql.JSONB(), nullable=True),
        sa.Column("after_state", postgresql.JSONB(), nullable=False),
        sa.Column("request_id", sa.Uuid(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(
            ["actor_id"], ["users.id"], name="fk_guide_audit_actor", ondelete="SET NULL"
        ),
        sa.CheckConstraint(
            "action IN ('create', 'edit', 'submit', 'approve', 'reject', 'publish', 'unpublish')",
            name="ck_guide_audit_action",
        ),
    )
    op.create_index(
        "ix_guide_audit_target_created",
        "guide_audit_events",
        ["guide_id", "created_at"],
    )


def downgrade() -> None:
    op.drop_table("guide_audit_events")
    for name in (
        "ck_life_guide_published_review",
        "ck_life_guide_review_status",
        "ck_life_guide_version",
    ):
        op.drop_constraint(name, "life_guides", type_="check")
    op.drop_constraint("fk_life_guide_reviewer", "life_guides", type_="foreignkey")
    for name in (
        "updated_at",
        "reviewed_at",
        "reviewed_by",
        "review_note",
        "review_status",
        "version",
    ):
        op.drop_column("life_guides", name)
