"""Recipe ingredient -> food mappings and computed recipe nutrition, derived from stored revisions.

Rows are computed by app.jobs.map_recipe_foods from an active recipe revision's ingredients and the
active food revisions (agetech_data.nutrition.recipe_map). Source nutrition printed by the recipe
provider stays on recipe_revisions (source_*); these tables hold only the computed estimate.
"""

import uuid
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.base import Base

MATCH_STATUSES = (
    "reviewed",
    "curated",
    "exact",
    "water",
    "excluded",  # Alembic 20261114_01: not eaten / already counted elsewhere (ingredient_food_map exclude)
    "candidate",
    "unmapped",
)
USABLE_STATUSES = ("reviewed", "curated", "exact")
GRAM_STATUSES = (
    "direct",
    "direct_paren",
    "approx_ml",
    "unit_weight",  # Alembic 20261113_01: sourced per-unit weight (agetech_data unit_weights.json)
    "count_unit",
    "qualitative",
    "missing",
    "unparsed",
)


def _in(column: str, values: tuple[str, ...]) -> str:
    return "{} IN ({})".format(column, ", ".join(f"'{value}'" for value in values))


class RecipeIngredientFood(Base):
    __tablename__ = "recipe_ingredient_foods"
    __table_args__ = (
        UniqueConstraint("recipe_ingredient_id", name="uq_recipe_ingredient_food"),
        ForeignKeyConstraint(
            ["recipe_revision_id", "recipe_ingredient_id"],
            ["recipe_ingredients.recipe_revision_id", "recipe_ingredients.id"],
            name="fk_recipe_ingredient_food_owned",
        ),
        ForeignKeyConstraint(
            ["food_id", "food_revision_id"],
            ["food_revisions.food_id", "food_revisions.id"],
            name="fk_recipe_ingredient_food_revision",
        ),
        CheckConstraint(
            _in("match_status", MATCH_STATUSES), name="ck_recipe_ingredient_match"
        ),
        CheckConstraint(
            _in("gram_status", GRAM_STATUSES), name="ck_recipe_ingredient_grams"
        ),
        # A usable match always names the exact food revision used; other statuses name none.
        CheckConstraint(
            "(food_id IS NULL) = (food_revision_id IS NULL) AND "
            f"({_in('match_status', USABLE_STATUSES)}) = "
            "(food_id IS NOT NULL)",
            name="ck_recipe_ingredient_food_present",
        ),
        CheckConstraint(
            "contribution IS NULL OR (food_revision_id IS NOT NULL AND grams IS NOT NULL)",
            name="ck_recipe_ingredient_contribution",
        ),
        CheckConstraint("grams IS NULL OR grams >= 0", name="ck_recipe_ingredient_g"),
        CheckConstraint(
            "(reviewed_by IS NULL) OR (match_status = 'reviewed')",
            name="ck_recipe_ingredient_review",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    recipe_revision_id: Mapped[uuid.UUID] = mapped_column(index=True)
    recipe_ingredient_id: Mapped[uuid.UUID]
    order_no: Mapped[int]
    match_status: Mapped[str] = mapped_column(String(16))
    match_rule: Mapped[str | None] = mapped_column(String(64))
    match_rationale: Mapped[str | None] = mapped_column(Text)
    candidates: Mapped[list] = mapped_column(JSONB, server_default=text("'[]'::jsonb"))
    food_id: Mapped[uuid.UUID | None] = mapped_column(index=True)
    food_revision_id: Mapped[uuid.UUID | None]
    reviewed_by: Mapped[str | None] = mapped_column(String(64))
    reviewed_on: Mapped[date | None]
    grams: Mapped[Decimal | None] = mapped_column(Numeric)
    gram_status: Mapped[str] = mapped_column(String(16))
    gram_basis: Mapped[str] = mapped_column(Text)
    # None must be SQL NULL (not JSON null) so the contribution CHECK and IS NULL queries work.
    contribution: Mapped[dict | None] = mapped_column(JSONB(none_as_null=True))
    basis_ml_approx: Mapped[bool] = mapped_column(server_default="false")


class RecipeComputedNutrition(Base):
    __tablename__ = "recipe_computed_nutrition"
    __table_args__ = (
        UniqueConstraint("recipe_revision_id", name="uq_recipe_computed_revision"),
        ForeignKeyConstraint(
            ["recipe_id", "recipe_revision_id"],
            ["recipe_revisions.recipe_id", "recipe_revisions.id"],
            name="fk_recipe_computed_owned_revision",
        ),
        CheckConstraint(
            "items_used >= 0 AND items_used <= items", name="ck_recipe_computed_items"
        ),
        CheckConstraint(
            "grams_used_pct IS NULL OR (grams_used_pct >= 0 AND grams_used_pct <= 100)",
            name="ck_recipe_computed_pct",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    recipe_id: Mapped[uuid.UUID] = mapped_column(index=True)
    recipe_revision_id: Mapped[uuid.UUID]
    computed: Mapped[dict] = mapped_column(JSONB)
    computed_missing: Mapped[dict] = mapped_column(JSONB)
    coverage: Mapped[dict] = mapped_column(JSONB)
    complete: Mapped[bool]
    items: Mapped[int]
    items_used: Mapped[int]
    grams_used_pct: Mapped[Decimal | None] = mapped_column(Numeric)
    mapper_version: Mapped[str] = mapped_column(String(64))
    ingredient_map_sha256: Mapped[str] = mapped_column(String(64))
    mapping_sha256: Mapped[str] = mapped_column(String(64))
    mapping_run_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("data_import_runs.id", name="fk_recipe_computed_run")
    )
    computed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
