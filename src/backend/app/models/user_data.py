import uuid
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Numeric,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.base import Base


class MealLog(Base):
    __tablename__ = "meal_logs"
    __table_args__ = (Index("ix_meal_logs_user_eaten", "user_id", "eaten_at"),)

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE")
    )
    eaten_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
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
