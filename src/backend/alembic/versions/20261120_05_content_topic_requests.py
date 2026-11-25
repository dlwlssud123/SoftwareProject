"""Private content requests, retry receipts and metadata-only moderation history."""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "20261120_05"
down_revision = "20261120_04"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "content_topic_requests",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "user_id",
            sa.Uuid(),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("submission_id", sa.Uuid(), nullable=False),
        sa.Column("fingerprint", sa.String(64), nullable=False),
        sa.Column("kind", sa.String(16), nullable=False),
        sa.Column("topic", sa.String(60), nullable=True),
        sa.Column("status", sa.String(16), server_default="received", nullable=False),
        sa.Column("version", sa.Integer(), server_default="1", nullable=False),
        sa.Column("reply", sa.Text(), nullable=True),
        sa.Column(
            "guide_id",
            sa.Uuid(),
            sa.ForeignKey("life_guides.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "reviewed_by",
            sa.Uuid(),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
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
        sa.UniqueConstraint("user_id", "submission_id", name="uq_topic_submission"),
        sa.CheckConstraint("kind IN ('life_guide', 'video')", name="ck_topic_kind"),
        sa.CheckConstraint(
            "status IN ('received', 'reviewing', 'completed', 'declined', 'withdrawn')",
            name="ck_topic_status",
        ),
        sa.CheckConstraint("version > 0", name="ck_topic_version"),
        sa.CheckConstraint(
            "(status = 'withdrawn' AND topic IS NULL AND reply IS NULL AND guide_id IS NULL) OR (status <> 'withdrawn' AND topic IS NOT NULL AND length(btrim(topic)) BETWEEN 1 AND 60)",
            name="ck_topic_content",
        ),
        sa.CheckConstraint(
            "reply IS NULL OR length(btrim(reply)) BETWEEN 1 AND 1000",
            name="ck_topic_reply",
        ),
        sa.CheckConstraint(
            "status NOT IN ('completed', 'declined') OR reply IS NOT NULL",
            name="ck_topic_decision",
        ),
        sa.CheckConstraint(
            "guide_id IS NULL OR (kind = 'life_guide' AND status = 'completed')",
            name="ck_topic_guide",
        ),
    )
    op.create_index(
        "ix_topic_owner_created", "content_topic_requests", ["user_id", "created_at"]
    )
    op.create_index(
        "ix_topic_queue", "content_topic_requests", ["status", "created_at"]
    )
    op.create_table(
        "topic_request_audit",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "topic_request_id",
            sa.Uuid(),
            sa.ForeignKey("content_topic_requests.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "actor_id",
            sa.Uuid(),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
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
        sa.CheckConstraint(
            "action IN ('create', 'review', 'withdraw')", name="ck_topic_audit_action"
        ),
    )
    op.create_index(
        "ix_topic_audit_created",
        "topic_request_audit",
        ["topic_request_id", "created_at"],
    )


def downgrade() -> None:
    op.drop_table("topic_request_audit")
    op.drop_table("content_topic_requests")
