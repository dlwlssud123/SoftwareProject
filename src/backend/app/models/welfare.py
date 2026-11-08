import uuid
from datetime import datetime

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.base import Base


class WelfareService(Base):
    __tablename__ = "welfare_services"
    __table_args__ = (
        UniqueConstraint("provider", "source_id", name="uq_welfare_service_source"),
        CheckConstraint(
            "publication_status IN ('published', 'missing', 'withdrawn', 'hold')",
            name="ck_welfare_publication",
        ),
        CheckConstraint("missing_scans >= 0", name="ck_welfare_missing_scans"),
        ForeignKeyConstraint(
            ["id", "active_revision_id"],
            ["welfare_revisions.service_id", "welfare_revisions.id"],
            name="fk_welfare_active_owned_revision",
            use_alter=True,
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    provider: Mapped[str] = mapped_column(String(64))
    source_id: Mapped[str] = mapped_column(String(64))
    scope: Mapped[str] = mapped_column(String(64), index=True)
    publication_status: Mapped[str] = mapped_column(String(16))
    active_revision_id: Mapped[uuid.UUID | None]
    last_checked_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    last_detail_checked_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True)
    )
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    last_seen_run_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("data_import_runs.id")
    )
    missing_scans: Mapped[int] = mapped_column(Integer, default=0)


class WelfareRevision(Base):
    __tablename__ = "welfare_revisions"
    __table_args__ = (
        UniqueConstraint(
            "service_id", "fingerprint", name="uq_welfare_revision_fingerprint"
        ),
        UniqueConstraint("service_id", "id", name="uq_welfare_revision_owner"),
        CheckConstraint(
            "quality_status IN ('ok', 'flagged', 'hold')", name="ck_welfare_quality"
        ),
        CheckConstraint(
            "application_status = 'unknown'",
            name="ck_welfare_service_application_unknown",
        ),
        CheckConstraint(
            "detail_state IN ('ready', 'pending')", name="ck_welfare_detail_state"
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    service_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("welfare_services.id"), index=True
    )
    import_run_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("data_import_runs.id"))
    fingerprint: Mapped[str] = mapped_column(String(64))
    normalizer_version: Mapped[str] = mapped_column(String(64))
    raw: Mapped[dict] = mapped_column(JSONB)
    raw_sha256: Mapped[str] = mapped_column(String(64))
    normalized: Mapped[dict] = mapped_column(JSONB)
    content_sha256: Mapped[str] = mapped_column(String(64))
    title: Mapped[str] = mapped_column(Text)
    summary: Mapped[str] = mapped_column(Text)
    target_text: Mapped[str] = mapped_column(Text)
    selection_text: Mapped[str] = mapped_column(Text)
    benefit_text: Mapped[str] = mapped_column(Text)
    application: Mapped[list] = mapped_column(JSONB)
    contacts: Mapped[list] = mapped_column(JSONB)
    source_url: Mapped[str] = mapped_column(Text)
    criteria_year: Mapped[str | None] = mapped_column(String(16))
    quality_status: Mapped[str] = mapped_column(String(16))
    detail_state: Mapped[str] = mapped_column(String(16))
    issues: Mapped[list] = mapped_column(JSONB)
    application_status: Mapped[str] = mapped_column(String(16), default="unknown")


class WelfareNotice(Base):
    __tablename__ = "welfare_notices"
    __table_args__ = (
        UniqueConstraint(
            "service_id", "source_notice_id", name="uq_welfare_notice_source"
        ),
        ForeignKeyConstraint(
            ["service_id", "source_revision_id"],
            ["welfare_revisions.service_id", "welfare_revisions.id"],
            name="fk_welfare_notice_owned_revision",
        ),
        CheckConstraint(
            "status IN ('unknown', 'scheduled', 'open', 'closed', 'withdrawn')",
            name="ck_welfare_notice_status",
        ),
        CheckConstraint(
            "period_type IN ('unknown', 'fixed', 'ongoing')",
            name="ck_welfare_notice_period",
        ),
        CheckConstraint(
            "(period_type = 'fixed' AND deadline_at IS NOT NULL) OR (period_type IN ('unknown', 'ongoing') AND starts_at IS NULL AND deadline_at IS NULL)",
            name="ck_welfare_notice_period_dates",
        ),
        CheckConstraint(
            "starts_at IS NULL OR starts_at < deadline_at",
            name="ck_welfare_notice_date_order",
        ),
        CheckConstraint(
            "status <> 'open' OR period_type <> 'unknown'",
            name="ck_welfare_notice_open_verified",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    service_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("welfare_services.id"), index=True
    )
    source_revision_id: Mapped[uuid.UUID] = mapped_column()
    source_notice_id: Mapped[str] = mapped_column(String(128))
    source_url: Mapped[str] = mapped_column(Text)
    period_text: Mapped[str] = mapped_column(Text)
    period_type: Mapped[str] = mapped_column(String(16))
    status: Mapped[str] = mapped_column(String(16), index=True)
    starts_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    deadline_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), index=True
    )
    checked_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
