import uuid
from datetime import datetime

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.base import Base


class ContentTopicRequest(Base):
    __tablename__ = "content_topic_requests"
    __table_args__ = (
        UniqueConstraint("user_id", "submission_id", name="uq_topic_submission"),
        Index("ix_topic_owner_created", "user_id", "created_at"),
        Index("ix_topic_queue", "status", "created_at"),
        CheckConstraint("kind IN ('life_guide', 'video')", name="ck_topic_kind"),
        CheckConstraint(
            "status IN ('received', 'reviewing', 'completed', 'declined', 'withdrawn')",
            name="ck_topic_status",
        ),
        CheckConstraint("version > 0", name="ck_topic_version"),
        CheckConstraint(
            "was_submitted OR status = 'withdrawn'", name="ck_topic_submission_state"
        ),
        CheckConstraint(
            "(status = 'withdrawn' AND topic IS NULL AND reply IS NULL AND guide_id IS NULL) OR (status <> 'withdrawn' AND topic IS NOT NULL AND length(btrim(topic)) BETWEEN 1 AND 60)",
            name="ck_topic_content",
        ),
        CheckConstraint(
            "reply IS NULL OR length(btrim(reply)) BETWEEN 1 AND 1000",
            name="ck_topic_reply",
        ),
        CheckConstraint(
            "status NOT IN ('completed', 'declined') OR reply IS NOT NULL",
            name="ck_topic_decision",
        ),
        CheckConstraint(
            "guide_id IS NULL OR (kind = 'life_guide' AND status = 'completed')",
            name="ck_topic_guide",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE")
    )
    submission_id: Mapped[uuid.UUID]
    fingerprint: Mapped[str] = mapped_column(String(64))
    was_submitted: Mapped[bool] = mapped_column(Boolean, server_default="true")
    kind: Mapped[str] = mapped_column(String(16))
    topic: Mapped[str | None] = mapped_column(String(60))
    status: Mapped[str] = mapped_column(String(16), server_default="received")
    version: Mapped[int] = mapped_column(server_default="1")
    reply: Mapped[str | None] = mapped_column(Text)
    guide_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("life_guides.id", ondelete="SET NULL")
    )
    reviewed_by: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class TopicRequestAudit(Base):
    __tablename__ = "topic_request_audit"
    __table_args__ = (
        Index("ix_topic_audit_created", "topic_request_id", "created_at"),
        CheckConstraint(
            "action IN ('create', 'review', 'withdraw')", name="ck_topic_audit_action"
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    topic_request_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("content_topic_requests.id", ondelete="CASCADE")
    )
    actor_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )
    action: Mapped[str] = mapped_column(String(16))
    before_state: Mapped[dict | None] = mapped_column(JSONB)
    after_state: Mapped[dict] = mapped_column(JSONB)
    request_id: Mapped[uuid.UUID]
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
