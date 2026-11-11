import uuid
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.base import Base

# Rows imported from public data carry all provenance columns; manually entered rows carry none.
_FACILITY_SOURCE_COLUMNS = (
    "provider",
    "source_id",
    "normalized",
    "content_sha256",
    "last_seen_at",
    "last_seen_run_id",
)


def _all_or_none(columns: tuple[str, ...]) -> str:
    return "({}) OR ({})".format(
        " AND ".join(f"{column} IS NULL" for column in columns),
        " AND ".join(f"{column} IS NOT NULL" for column in columns),
    )


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
        UniqueConstraint("provider", "source_id", name="uq_meal_facility_source"),
        CheckConstraint(
            _all_or_none(_FACILITY_SOURCE_COLUMNS),
            name="ck_meal_facility_source_complete",
        ),
        CheckConstraint(
            "jsonb_typeof(quality_flags) = 'array'", name="ck_meal_facility_flags"
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
    # Public-data provenance (agetech_data.facilities.revision); NULL for manual entries.
    provider: Mapped[str | None] = mapped_column(String(64))
    source_id: Mapped[str | None] = mapped_column(String(64))
    reference_date: Mapped[date | None]
    quality_flags: Mapped[list] = mapped_column(
        JSONB, server_default=text("'[]'::jsonb")
    )
    normalized: Mapped[dict | None] = mapped_column(JSONB)
    content_sha256: Mapped[str | None] = mapped_column(String(64))
    last_seen_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_seen_run_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("data_import_runs.id", name="fk_meal_facility_last_seen_run")
    )


class SeasonalFood(Base):
    """One official 'food of the month' item (month, source sequence) with its detail text."""

    __tablename__ = "seasonal_foods"
    __table_args__ = (
        UniqueConstraint("provider", "source_id", name="uq_seasonal_food_source"),
        UniqueConstraint("id", "month", name="uq_seasonal_food_month"),
        CheckConstraint("month BETWEEN 1 AND 12", name="ck_seasonal_food_month"),
        CheckConstraint(
            "detail_status IN ('ok', 'failed')", name="ck_seasonal_food_detail"
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    provider: Mapped[str] = mapped_column(String(64))
    source_id: Mapped[str] = mapped_column(String(32))
    month: Mapped[int]
    fdmt_sn: Mapped[str] = mapped_column(String(32))
    name: Mapped[str] = mapped_column(String(128))
    terms: Mapped[list] = mapped_column(JSONB)
    image_url: Mapped[str | None] = mapped_column(Text)
    detail: Mapped[dict] = mapped_column(JSONB)
    detail_status: Mapped[str] = mapped_column(String(16))
    official_related_recipes: Mapped[list] = mapped_column(JSONB)
    shopping_search_url: Mapped[str] = mapped_column(Text)
    source_url: Mapped[str] = mapped_column(Text)
    checked_on: Mapped[date]
    normalized: Mapped[dict] = mapped_column(JSONB)
    content_sha256: Mapped[str] = mapped_column(String(64))
    links_sha256: Mapped[str] = mapped_column(String(64))
    is_published: Mapped[bool] = mapped_column(server_default="false")
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    last_seen_run_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("data_import_runs.id", name="fk_seasonal_food_last_seen_run")
    )


class SeasonalIngredient(Base):
    __tablename__ = "seasonal_ingredients"
    __table_args__ = (
        UniqueConstraint(
            "month", "recipe_ingredient_name", name="uq_seasonal_month_recipe_name"
        ),
        CheckConstraint("month BETWEEN 1 AND 12", name="ck_seasonal_month"),
        ForeignKeyConstraint(
            ["seasonal_food_id", "month"],
            ["seasonal_foods.id", "seasonal_foods.month"],
            name="fk_seasonal_ingredient_food_month",
            ondelete="CASCADE",
        ),
        CheckConstraint(
            "(seasonal_food_id IS NULL AND match_term IS NULL AND match_kind IS NULL) OR "
            "(seasonal_food_id IS NOT NULL AND match_term IS NOT NULL "
            "AND match_kind IS NOT NULL AND match_kind IN ('official', 'alias'))",
            name="ck_seasonal_ingredient_match",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    month: Mapped[int]
    ingredient_name: Mapped[str] = mapped_column(String(128))
    recipe_ingredient_name: Mapped[str] = mapped_column(Text)
    source_url: Mapped[str] = mapped_column(Text)
    checked_on: Mapped[date]
    is_published: Mapped[bool] = mapped_column(server_default="false")
    # Rule-based match evidence (resources/seasonal_terms.json); NULL for manual entries.
    seasonal_food_id: Mapped[uuid.UUID | None] = mapped_column(index=True)
    match_term: Mapped[str | None] = mapped_column(Text)
    match_kind: Mapped[str | None] = mapped_column(String(16))


class SeasonalRecipeLink(Base):
    """A recipe containing a seasonal food, linked against one recipe revision."""

    __tablename__ = "seasonal_recipe_links"
    __table_args__ = (
        UniqueConstraint(
            "seasonal_food_id", "recipe_id", name="uq_seasonal_recipe_link"
        ),
        ForeignKeyConstraint(
            ["recipe_id", "recipe_revision_id"],
            ["recipe_revisions.recipe_id", "recipe_revisions.id"],
            name="fk_seasonal_link_owned_revision",
        ),
        CheckConstraint(
            "share IS NULL OR (share >= 0 AND share <= 1)",
            name="ck_seasonal_link_share",
        ),
        CheckConstraint(
            "(share IS NULL) = (weight_g IS NULL)", name="ck_seasonal_link_weight"
        ),
        Index("ix_seasonal_recipe_links_recipe", "recipe_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    seasonal_food_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey(
            "seasonal_foods.id", name="fk_seasonal_link_food", ondelete="CASCADE"
        ),
        index=True,
    )
    recipe_id: Mapped[uuid.UUID]
    recipe_revision_id: Mapped[uuid.UUID]
    ingredient_names: Mapped[list] = mapped_column(JSONB)
    weight_g: Mapped[Decimal | None] = mapped_column(Numeric)
    share: Mapped[Decimal | None] = mapped_column(Numeric)
