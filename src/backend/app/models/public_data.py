"""Source records and immutable parsed revisions, separate from user meal records."""

import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.base import Base


class DataImportRun(Base):
    __tablename__ = "data_import_runs"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    fingerprint: Mapped[str] = mapped_column(String(64), unique=True)
    parser_version: Mapped[str] = mapped_column(String(64))
    inputs: Mapped[dict] = mapped_column(JSONB)
    counts: Mapped[dict] = mapped_column(JSONB)
    completed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class Recipe(Base):
    __tablename__ = "recipes"
    __table_args__ = (
        UniqueConstraint("provider", "source_id", name="uq_recipes_source"),
        ForeignKeyConstraint(
            ["id", "active_revision_id"],
            ["recipe_revisions.recipe_id", "recipe_revisions.id"],
            name="fk_recipe_active_owned_revision",
            use_alter=True,
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    provider: Mapped[str] = mapped_column(String(64))
    source_id: Mapped[str] = mapped_column(String(64))
    active_revision_id: Mapped[uuid.UUID | None]


class RecipeRevision(Base):
    __tablename__ = "recipe_revisions"
    __table_args__ = (
        UniqueConstraint(
            "recipe_id", "fingerprint", name="uq_recipe_revision_fingerprint"
        ),
        UniqueConstraint("recipe_id", "id", name="uq_recipe_revision_owner"),
        CheckConstraint(
            "quality_status IN ('ok', 'flagged', 'hold')", name="ck_recipe_quality"
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    recipe_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("recipes.id"), index=True)
    import_run_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("data_import_runs.id"))
    fingerprint: Mapped[str] = mapped_column(String(64))
    raw_sha256: Mapped[str] = mapped_column(String(64))
    effective_sha256: Mapped[str] = mapped_column(String(64))
    raw: Mapped[dict] = mapped_column(JSONB)
    effective: Mapped[dict] = mapped_column(JSONB)
    corrections: Mapped[list] = mapped_column(JSONB)
    name: Mapped[str] = mapped_column(Text)
    method: Mapped[str | None] = mapped_column(Text)
    category: Mapped[str | None] = mapped_column(Text)
    quality_status: Mapped[str] = mapped_column(String(16))
    issues: Mapped[list] = mapped_column(JSONB)
    missing_step_nos: Mapped[list] = mapped_column(JSONB)
    nutrition_basis: Mapped[str] = mapped_column(
        String(64), default="per_serving_unverified"
    )
    source_weight_text: Mapped[str | None] = mapped_column(Text)
    source_energy_kcal: Mapped[Decimal | None] = mapped_column(Numeric)
    source_carbohydrate_g: Mapped[Decimal | None] = mapped_column(Numeric)
    source_protein_g: Mapped[Decimal | None] = mapped_column(Numeric)
    source_fat_g: Mapped[Decimal | None] = mapped_column(Numeric)
    source_sodium_mg: Mapped[Decimal | None] = mapped_column(Numeric)


class RecipeStep(Base):
    __tablename__ = "recipe_steps"
    __table_args__ = (
        UniqueConstraint(
            "recipe_revision_id", "source_no", name="uq_recipe_step_number"
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    recipe_revision_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("recipe_revisions.id"), index=True
    )
    source_no: Mapped[int] = mapped_column(Integer)
    stated_no: Mapped[int | None] = mapped_column(Integer)
    source_field: Mapped[str] = mapped_column(String(32))
    text_raw: Mapped[str] = mapped_column(Text)
    text_clean: Mapped[str] = mapped_column(Text)
    image_url: Mapped[str | None] = mapped_column(Text)


class RecipeIngredient(Base):
    __tablename__ = "recipe_ingredients"
    __table_args__ = (
        UniqueConstraint(
            "recipe_revision_id", "order_no", name="uq_recipe_ingredient_order"
        ),
        # Lets derived rows (recipe_ingredient_foods) prove the ingredient belongs to their revision.
        UniqueConstraint("recipe_revision_id", "id", name="uq_recipe_ingredient_owner"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    recipe_revision_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("recipe_revisions.id"), index=True
    )
    order_no: Mapped[int] = mapped_column(Integer)
    line_no: Mapped[int] = mapped_column(Integer)
    section: Mapped[str] = mapped_column(Text)
    raw_item: Mapped[str] = mapped_column(Text)
    name_raw: Mapped[str] = mapped_column(Text)
    name: Mapped[str] = mapped_column(Text)
    amount_text: Mapped[str] = mapped_column(Text)
    unit: Mapped[str | None] = mapped_column(String(32))
    parsed: Mapped[dict] = mapped_column(JSONB)


class Food(Base):
    __tablename__ = "foods"
    __table_args__ = (
        UniqueConstraint("provider", "food_code", name="uq_foods_source"),
        ForeignKeyConstraint(
            ["id", "active_revision_id"],
            ["food_revisions.food_id", "food_revisions.id"],
            name="fk_food_active_owned_revision",
            use_alter=True,
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    provider: Mapped[str] = mapped_column(String(64))
    food_code: Mapped[str] = mapped_column(String(128))
    active_revision_id: Mapped[uuid.UUID | None]


class FoodRevision(Base):
    __tablename__ = "food_revisions"
    __table_args__ = (
        UniqueConstraint("food_id", "fingerprint", name="uq_food_revision_fingerprint"),
        UniqueConstraint("food_id", "id", name="uq_food_revision_owner"),
        CheckConstraint(
            "basis_amount IS NULL OR basis_amount > 0", name="ck_food_positive_basis"
        ),
        CheckConstraint(
            "basis_unit IS NULL OR basis_unit IN ('g', 'mL')", name="ck_food_basis_unit"
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    food_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("foods.id"), index=True)
    import_run_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("data_import_runs.id"))
    fingerprint: Mapped[str] = mapped_column(String(64))
    raw_sha256: Mapped[str] = mapped_column(String(64))
    raw: Mapped[dict] = mapped_column(JSONB)
    normalized: Mapped[dict] = mapped_column(JSONB)
    name: Mapped[str] = mapped_column(Text)
    basis_text: Mapped[str | None] = mapped_column(Text)
    basis_amount: Mapped[Decimal | None] = mapped_column(Numeric)
    basis_unit: Mapped[str | None] = mapped_column(String(8))
    nutrients: Mapped[dict] = mapped_column(JSONB)
    quality_flags: Mapped[list] = mapped_column(JSONB)
    energy_kcal: Mapped[Decimal | None] = mapped_column(Numeric)
    carbohydrate_g: Mapped[Decimal | None] = mapped_column(Numeric)
    protein_g: Mapped[Decimal | None] = mapped_column(Numeric)
    fat_g: Mapped[Decimal | None] = mapped_column(Numeric)
    sugars_g: Mapped[Decimal | None] = mapped_column(Numeric)
    fiber_g: Mapped[Decimal | None] = mapped_column(Numeric)
    sodium_mg: Mapped[Decimal | None] = mapped_column(Numeric)
