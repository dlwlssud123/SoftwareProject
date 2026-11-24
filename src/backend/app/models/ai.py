"""Daily request counters only; prompts and photos are not persisted."""

from datetime import date

from sqlalchemy import CheckConstraint, Date, String
from sqlalchemy.orm import Mapped, mapped_column

from app.core.base import Base


class AIUsageBucket(Base):
    __tablename__ = "ai_usage_buckets"
    __table_args__ = (CheckConstraint("calls > 0", name="ck_ai_usage_positive"),)

    bucket_id: Mapped[str] = mapped_column(String(80), primary_key=True)
    usage_date: Mapped[date] = mapped_column(Date, primary_key=True)
    calls: Mapped[int]
