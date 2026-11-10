import uuid
from datetime import date
from decimal import Decimal

from sqlalchemy import CheckConstraint, Index, Numeric, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.base import Base


class LifeGuide(Base):
    __tablename__ = "life_guides"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    slug: Mapped[str] = mapped_column(String(128), unique=True)
    title: Mapped[str] = mapped_column(Text)
    steps: Mapped[list] = mapped_column(JSONB)
    source_reference: Mapped[str] = mapped_column(Text)
    checked_on: Mapped[date]
    is_published: Mapped[bool] = mapped_column(server_default="false")


class MealFacility(Base):
    __tablename__ = "meal_facilities"
    __table_args__ = (
        Index("ix_meal_facilities_region", "sido", "sigungu"),
        CheckConstraint(
            "(latitude IS NULL AND longitude IS NULL) OR "
            "(latitude IS NOT NULL AND longitude IS NOT NULL "
            "AND latitude BETWEEN -90 AND 90 AND longitude BETWEEN -180 AND 180)",
            name="ck_meal_facility_coordinates",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(Text)
    sido: Mapped[str] = mapped_column(String(64))
    sigungu: Mapped[str] = mapped_column(String(64))
    address: Mapped[str | None] = mapped_column(Text)
    latitude: Mapped[Decimal | None] = mapped_column(Numeric(8, 5))
    longitude: Mapped[Decimal | None] = mapped_column(Numeric(8, 5))
    eligibility_text: Mapped[str | None] = mapped_column(Text)
    hours_text: Mapped[str | None] = mapped_column(Text)
    contact_text: Mapped[str | None] = mapped_column(Text)
    source_url: Mapped[str] = mapped_column(Text)
    checked_on: Mapped[date]
    is_published: Mapped[bool] = mapped_column(server_default="false")


class SeasonalIngredient(Base):
    __tablename__ = "seasonal_ingredients"
    __table_args__ = (
        UniqueConstraint(
            "month", "recipe_ingredient_name", name="uq_seasonal_month_recipe_name"
        ),
        CheckConstraint("month BETWEEN 1 AND 12", name="ck_seasonal_month"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    month: Mapped[int]
    ingredient_name: Mapped[str] = mapped_column(String(128))
    recipe_ingredient_name: Mapped[str] = mapped_column(Text)
    source_url: Mapped[str] = mapped_column(Text)
    checked_on: Mapped[date]
    is_published: Mapped[bool] = mapped_column(server_default="false")
