"""Add text community posts, private reports, and blocking."""

import sqlalchemy as sa

from alembic import op

revision = "20261124_01"
down_revision = "20261120_06"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "community_posts",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "author_id",
            sa.Uuid(),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("submission_id", sa.Uuid(), nullable=False),
        sa.Column("fingerprint", sa.String(64), nullable=False),
        sa.Column("category", sa.String(16), nullable=False),
        sa.Column("title", sa.String(60), nullable=False),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("status", sa.String(16), server_default="published", nullable=False),
        sa.Column("version", sa.Integer(), server_default="1", nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.UniqueConstraint(
            "author_id", "submission_id", name="uq_community_submission"
        ),
        sa.CheckConstraint(
            "category IN ('meal', 'daily')", name="ck_community_category"
        ),
        sa.CheckConstraint(
            "status IN ('published', 'hidden', 'deleted')",
            name="ck_community_post_status",
        ),
        sa.CheckConstraint("version >= 1", name="ck_community_post_version"),
        sa.CheckConstraint(
            "char_length(title) <= 60 AND char_length(body) <= 2000",
            name="ck_community_post_length",
        ),
    )
    op.create_index(
        "ix_community_post_feed", "community_posts", ["status", "created_at", "id"]
    )
    op.create_index(
        "ix_community_post_author", "community_posts", ["author_id", "created_at"]
    )
    op.create_table(
        "community_blocks",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "viewer_id",
            sa.Uuid(),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "blocked_id",
            sa.Uuid(),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.UniqueConstraint("viewer_id", "blocked_id", name="uq_community_block"),
        sa.CheckConstraint(
            "viewer_id <> blocked_id", name="ck_community_block_not_self"
        ),
    )
    op.create_index(
        "ix_community_block_reverse", "community_blocks", ["blocked_id", "viewer_id"]
    )
    op.create_table(
        "community_reports",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "post_id",
            sa.Uuid(),
            sa.ForeignKey("community_posts.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "reporter_id",
            sa.Uuid(),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("reason", sa.String(24), nullable=False),
        sa.Column("note", sa.String(500), nullable=False),
        sa.Column("status", sa.String(16), server_default="received", nullable=False),
        sa.Column("resolution", sa.String(200), server_default="", nullable=False),
        sa.Column(
            "reviewer_id", sa.Uuid(), sa.ForeignKey("users.id", ondelete="SET NULL")
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("reviewed_at", sa.DateTime(timezone=True)),
        sa.UniqueConstraint("post_id", "reporter_id", name="uq_community_report"),
        sa.CheckConstraint(
            "reason IN ('spam', 'abuse', 'misinformation', 'privacy', 'other')",
            name="ck_community_report_reason",
        ),
        sa.CheckConstraint(
            "status IN ('received', 'dismissed', 'actioned')",
            name="ck_community_report_status",
        ),
        sa.CheckConstraint(
            "char_length(note) <= 500 AND char_length(resolution) <= 200",
            name="ck_community_report_length",
        ),
    )
    op.create_index(
        "ix_community_report_queue", "community_reports", ["status", "created_at", "id"]
    )


def downgrade() -> None:
    op.drop_table("community_reports")
    op.drop_table("community_blocks")
    op.drop_table("community_posts")
