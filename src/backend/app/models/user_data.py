import uuid
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    UniqueConstraint,
    Uuid,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.base import Base


class MealLog(Base):
    __tablename__ = "meal_logs"
    __table_args__ = (
        Index("ix_meal_logs_user_eaten", "user_id", "eaten_at"),
        CheckConstraint("version > 0", name="ck_meal_log_version"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE")
    )
    eaten_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    version: Mapped[int] = mapped_column(Integer, server_default="1")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class MealLogItem(Base):
    __tablename__ = "meal_log_items"
    __table_args__ = (
        CheckConstraint(
            "amount > 0 AND amount <> 'NaN'",
            name="ck_meal_log_item_portion",
        ),
        CheckConstraint("amount_unit IN ('g', 'mL')", name="ck_meal_log_item_unit"),
        CheckConstraint("order_no IS NULL OR order_no > 0", name="ck_meal_item_order"),
        UniqueConstraint("meal_log_id", "order_no", name="uq_meal_item_order"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    meal_log_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("meal_logs.id", ondelete="CASCADE"), index=True
    )
    food_revision_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("food_revisions.id"))
    amount: Mapped[Decimal] = mapped_column(Numeric(10, 3))
    amount_unit: Mapped[str] = mapped_column(String(2))
    nutrients: Mapped[dict] = mapped_column(JSONB)
    calculation_version: Mapped[str] = mapped_column(String(64))
    order_no: Mapped[int | None] = mapped_column(Integer)
    portion_snapshot: Mapped[dict | None] = mapped_column(JSONB)


class MealCreateRequest(Base):
    """Keep only hashes and a nullable link so a deleted meal cannot be recreated by retry."""

    __tablename__ = "meal_create_requests"

    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    key_hash: Mapped[str] = mapped_column(String(64), primary_key=True)
    request_hash: Mapped[str] = mapped_column(String(64))
    meal_log_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("meal_logs.id", ondelete="SET NULL"), index=True
    )


class RecommendationRun(Base):
    __tablename__ = "recommendation_runs"
    __table_args__ = (
        Index("ix_recommendation_runs_user_evaluated", "user_id", "evaluated_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE")
    )
    meal_time: Mapped[str] = mapped_column(String(16))
    rules_version: Mapped[str] = mapped_column(String(64))
    evaluated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class RecommendationItem(Base):
    __tablename__ = "recommendation_items"

    run_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("recommendation_runs.id", ondelete="CASCADE"), primary_key=True
    )
    rank: Mapped[int] = mapped_column(primary_key=True)
    recipe_revision_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("recipe_revisions.id")
    )
    reasons: Mapped[list] = mapped_column(JSONB)
    seasonal_ingredients: Mapped[list] = mapped_column(JSONB)


class SavedRecipe(Base):
    __tablename__ = "saved_recipes"

    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    recipe_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("recipes.id"), primary_key=True
    )
    saved_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class SavedWelfareService(Base):
    __tablename__ = "saved_welfare_services"

    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    service_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("welfare_services.id"), primary_key=True
    )
    saved_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    progress_note: Mapped[str | None] = mapped_column(String(2000))
    note_updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class MealPlanEntry(Base):
    __tablename__ = "meal_plan_entries"
    __table_args__ = (
        UniqueConstraint(
            "user_id", "plan_date", "meal_slot", name="uq_meal_plan_user_date_slot"
        ),
        CheckConstraint(
            "meal_slot IN ('breakfast', 'lunch', 'dinner', 'snack', 'special')",
            name="ck_meal_plan_slot",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE")
    )
    plan_date: Mapped[date]
    meal_slot: Mapped[str] = mapped_column(String(16))
    recipe_revision_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("recipe_revisions.id")
    )
