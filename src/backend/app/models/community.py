"""Text community content, private reports, and viewer-specific blocking."""

import uuid
from datetime import datetime

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.core.base import Base


class CommunityPost(Base):
    __tablename__ = "community_posts"
    __table_args__ = (
        UniqueConstraint("author_id", "submission_id", name="uq_community_submission"),
        CheckConstraint("category IN ('meal', 'daily')", name="ck_community_category"),
        CheckConstraint(
            "status IN ('published', 'hidden', 'deleted')",
            name="ck_community_post_status",
        ),
        CheckConstraint("version >= 1", name="ck_community_post_version"),
        CheckConstraint(
            "char_length(title) <= 60 AND char_length(body) <= 2000",
            name="ck_community_post_length",
        ),
        Index("ix_community_post_feed", "status", "created_at", "id"),
        Index("ix_community_post_author", "author_id", "created_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    author_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE")
    )
    submission_id: Mapped[uuid.UUID]
    fingerprint: Mapped[str] = mapped_column(String(64))
    category: Mapped[str] = mapped_column(String(16))
    title: Mapped[str] = mapped_column(String(60))
    body: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(16), server_default="published")
    version: Mapped[int] = mapped_column(server_default="1")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class CommunityBlock(Base):
    __tablename__ = "community_blocks"
    __table_args__ = (
        UniqueConstraint("viewer_id", "blocked_id", name="uq_community_block"),
        CheckConstraint("viewer_id <> blocked_id", name="ck_community_block_not_self"),
        Index("ix_community_block_reverse", "blocked_id", "viewer_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    viewer_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE")
    )
    blocked_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE")
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class CommunityReport(Base):
    __tablename__ = "community_reports"
    __table_args__ = (
        UniqueConstraint("post_id", "reporter_id", name="uq_community_report"),
        CheckConstraint(
            "reason IN ('spam', 'abuse', 'misinformation', 'privacy', 'other')",
            name="ck_community_report_reason",
        ),
        CheckConstraint(
            "status IN ('received', 'dismissed', 'actioned')",
            name="ck_community_report_status",
        ),
        CheckConstraint(
            "char_length(note) <= 500 AND char_length(resolution) <= 200",
            name="ck_community_report_length",
        ),
        Index("ix_community_report_queue", "status", "created_at", "id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    post_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("community_posts.id", ondelete="CASCADE")
    )
    reporter_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE")
    )
    reason: Mapped[str] = mapped_column(String(24))
    note: Mapped[str] = mapped_column(String(500), default="")
    status: Mapped[str] = mapped_column(String(16), server_default="received")
    resolution: Mapped[str] = mapped_column(String(200), server_default="")
    reviewer_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
