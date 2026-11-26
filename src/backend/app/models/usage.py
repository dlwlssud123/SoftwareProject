"""Allowlisted usage metadata; never persist identities or free-form payloads."""

from datetime import datetime
from uuid import UUID

from sqlalchemy import CheckConstraint, DateTime, Index, String
from sqlalchemy.orm import Mapped, mapped_column

from app.core.base import Base


class UsageEvent(Base):
    __tablename__ = "usage_events"
    __table_args__ = (
        CheckConstraint(
            "duration_ms IS NULL OR duration_ms BETWEEN 0 AND 3600000",
            name="ck_usage_duration",
        ),
        CheckConstraint(
            "result_count IS NULL OR result_count BETWEEN 0 AND 1000000",
            name="ck_usage_count",
        ),
        Index("ix_usage_created", "created_at"),
        Index("ix_usage_collector_created", "collector_key", "created_at"),
        Index("ix_usage_feature_created", "feature", "created_at"),
    )
    collector_key: Mapped[str] = mapped_column(String(64), primary_key=True)
    event_id: Mapped[UUID] = mapped_column(primary_key=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    event: Mapped[str] = mapped_column(String(32))
    feature: Mapped[str] = mapped_column(String(24))
    action: Mapped[str] = mapped_column(String(16))
    outcome: Mapped[str] = mapped_column(String(16))
    app_version: Mapped[str] = mapped_column(String(32))
    platform: Mapped[str] = mapped_column(String(16))
    duration_ms: Mapped[int | None]
    error_kind: Mapped[str | None] = mapped_column(String(24))
    request_id: Mapped[UUID | None]
    result_count: Mapped[int | None]
    result_kind: Mapped[str | None] = mapped_column(String(24))
    setting_kind: Mapped[str | None] = mapped_column(String(16))
    setting_value: Mapped[str | None] = mapped_column(String(16))
