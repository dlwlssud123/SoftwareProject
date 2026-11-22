"""Keep administrator decisions independent of facility/seasonal source imports."""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "20261122_01"
down_revision = "20261120_06"
branch_labels = None
depends_on = None


def upgrade() -> None:
    for table, prefix in (
        ("meal_facilities", "facility"),
        ("seasonal_foods", "seasonal_food"),
    ):
        for column in (
            sa.Column(
                "review_version", sa.Integer(), server_default="1", nullable=False
            ),
            sa.Column(
                "review_status", sa.String(16), server_default="legacy", nullable=False
            ),
            sa.Column(
                "review_is_published",
                sa.Boolean(),
                server_default="true",
                nullable=False,
            ),
            sa.Column("reviewed_content_sha256", sa.String(64), nullable=True),
            sa.Column("review_note", sa.Text(), nullable=True),
            sa.Column("reviewed_by", sa.Uuid(), nullable=True),
            sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column(
                "review_updated_at",
                sa.DateTime(timezone=True),
                server_default=sa.func.now(),
                nullable=False,
            ),
        ):
            op.add_column(table, column)
        op.create_foreign_key(
            f"fk_{prefix}_reviewer",
            table,
            "users",
            ["reviewed_by"],
            ["id"],
            ondelete="SET NULL",
        )
        op.create_check_constraint(
            f"ck_{prefix}_review_version", table, "review_version > 0"
        )
        op.create_check_constraint(
            f"ck_{prefix}_review_status",
            table,
            "review_status IN ('legacy', 'review', 'approved', 'rejected')",
        )
        op.create_check_constraint(
            f"ck_{prefix}_review_publication",
            table,
            "NOT review_is_published OR review_status IN ('legacy', 'approved')",
        )
    # Legacy preserves the pre-existing automatic source rules, not a fictional approval.
    op.create_table(
        "catalog_audit_events",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("kind", sa.String(24), nullable=False),
        sa.Column("target_id", sa.Uuid(), nullable=False),
        sa.Column("actor_id", sa.Uuid(), nullable=True),
        sa.Column("action", sa.String(16), nullable=False),
        sa.Column("before_state", postgresql.JSONB(), nullable=False),
        sa.Column("after_state", postgresql.JSONB(), nullable=False),
        sa.Column("request_id", sa.Uuid(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["actor_id"],
            ["users.id"],
            name="fk_catalog_audit_actor",
            ondelete="SET NULL",
        ),
        sa.CheckConstraint(
            "kind IN ('meal-facilities', 'seasonal-foods')",
            name="ck_catalog_audit_kind",
        ),
        sa.CheckConstraint(
            "action IN ('submit', 'approve', 'reject', 'publish', 'unpublish')",
            name="ck_catalog_audit_action",
        ),
    )
    op.create_index(
        "ix_catalog_audit_target_created",
        "catalog_audit_events",
        ["kind", "target_id", "created_at"],
    )


def downgrade() -> None:
    op.drop_table("catalog_audit_events")
    for table, prefix in (
        ("meal_facilities", "facility"),
        ("seasonal_foods", "seasonal_food"),
    ):
        for name in ("publication", "status", "version"):
            op.drop_constraint(f"ck_{prefix}_review_{name}", table, type_="check")
        op.drop_constraint(f"fk_{prefix}_reviewer", table, type_="foreignkey")
        for name in (
            "review_updated_at",
            "reviewed_at",
            "reviewed_by",
            "review_note",
            "reviewed_content_sha256",
            "review_is_published",
            "review_status",
            "review_version",
        ):
            op.drop_column(table, name)
