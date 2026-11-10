"""Add recipe ingredient -> food mappings and computed recipe nutrition.

Revision ID: 20261111_02
Revises: 20261111_01
"""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "20261111_02"
down_revision = "20261111_01"
branch_labels = None
depends_on = None

MATCH_STATUSES = ("reviewed", "curated", "exact", "water", "candidate", "unmapped")
USABLE_STATUSES = ("reviewed", "curated", "exact")
GRAM_STATUSES = (
    "direct",
    "direct_paren",
    "approx_ml",
    "count_unit",
    "qualitative",
    "missing",
    "unparsed",
)


def _in(column: str, values: tuple[str, ...]) -> str:
    return "{} IN ({})".format(column, ", ".join(f"'{value}'" for value in values))


def upgrade() -> None:
    jsonb = postgresql.JSONB(astext_type=sa.Text())
    op.create_unique_constraint(
        "uq_recipe_ingredient_owner", "recipe_ingredients", ["recipe_revision_id", "id"]
    )
    op.create_table(
        "recipe_ingredient_foods",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("recipe_revision_id", sa.Uuid(), nullable=False),
        sa.Column("recipe_ingredient_id", sa.Uuid(), nullable=False),
        sa.Column("order_no", sa.Integer(), nullable=False),
        sa.Column("match_status", sa.String(length=16), nullable=False),
        sa.Column("match_rule", sa.String(length=64), nullable=True),
        sa.Column("match_rationale", sa.Text(), nullable=True),
        sa.Column(
            "candidates", jsonb, server_default=sa.text("'[]'::jsonb"), nullable=False
        ),
        sa.Column("food_id", sa.Uuid(), nullable=True),
        sa.Column("food_revision_id", sa.Uuid(), nullable=True),
        sa.Column("reviewed_by", sa.String(length=64), nullable=True),
        sa.Column("reviewed_on", sa.Date(), nullable=True),
        sa.Column("grams", sa.Numeric(), nullable=True),
        sa.Column("gram_status", sa.String(length=16), nullable=False),
        sa.Column("gram_basis", sa.Text(), nullable=False),
        sa.Column("contribution", jsonb, nullable=True),
        sa.Column(
            "basis_ml_approx", sa.Boolean(), server_default="false", nullable=False
        ),
        sa.CheckConstraint(
            _in("match_status", MATCH_STATUSES), name="ck_recipe_ingredient_match"
        ),
        sa.CheckConstraint(
            _in("gram_status", GRAM_STATUSES), name="ck_recipe_ingredient_grams"
        ),
        sa.CheckConstraint(
            f"({_in('match_status', USABLE_STATUSES)}) = "
            "(food_id IS NOT NULL AND food_revision_id IS NOT NULL)",
            name="ck_recipe_ingredient_food_present",
        ),
        sa.CheckConstraint(
            "contribution IS NULL OR (food_revision_id IS NOT NULL AND grams IS NOT NULL)",
            name="ck_recipe_ingredient_contribution",
        ),
        sa.CheckConstraint(
            "grams IS NULL OR grams >= 0", name="ck_recipe_ingredient_g"
        ),
        sa.CheckConstraint(
            "(reviewed_by IS NULL) OR (match_status = 'reviewed')",
            name="ck_recipe_ingredient_review",
        ),
        sa.ForeignKeyConstraint(
            ["food_id", "food_revision_id"],
            ["food_revisions.food_id", "food_revisions.id"],
            name="fk_recipe_ingredient_food_revision",
        ),
        sa.ForeignKeyConstraint(
            ["recipe_revision_id", "recipe_ingredient_id"],
            ["recipe_ingredients.recipe_revision_id", "recipe_ingredients.id"],
            name="fk_recipe_ingredient_food_owned",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("recipe_ingredient_id", name="uq_recipe_ingredient_food"),
    )
    op.create_index(
        op.f("ix_recipe_ingredient_foods_recipe_revision_id"),
        "recipe_ingredient_foods",
        ["recipe_revision_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_recipe_ingredient_foods_food_id"),
        "recipe_ingredient_foods",
        ["food_id"],
        unique=False,
    )
    op.create_table(
        "recipe_computed_nutrition",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("recipe_id", sa.Uuid(), nullable=False),
        sa.Column("recipe_revision_id", sa.Uuid(), nullable=False),
        sa.Column("computed", jsonb, nullable=False),
        sa.Column("computed_missing", jsonb, nullable=False),
        sa.Column("coverage", jsonb, nullable=False),
        sa.Column("complete", sa.Boolean(), nullable=False),
        sa.Column("items", sa.Integer(), nullable=False),
        sa.Column("items_used", sa.Integer(), nullable=False),
        sa.Column("grams_used_pct", sa.Numeric(), nullable=True),
        sa.Column("mapper_version", sa.String(length=64), nullable=False),
        sa.Column("ingredient_map_sha256", sa.String(length=64), nullable=False),
        sa.Column("mapping_sha256", sa.String(length=64), nullable=False),
        sa.Column("mapping_run_id", sa.Uuid(), nullable=False),
        sa.Column(
            "computed_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "items_used >= 0 AND items_used <= items", name="ck_recipe_computed_items"
        ),
        sa.CheckConstraint(
            "grams_used_pct IS NULL OR (grams_used_pct >= 0 AND grams_used_pct <= 100)",
            name="ck_recipe_computed_pct",
        ),
        sa.ForeignKeyConstraint(
            ["mapping_run_id"], ["data_import_runs.id"], name="fk_recipe_computed_run"
        ),
        sa.ForeignKeyConstraint(
            ["recipe_id", "recipe_revision_id"],
            ["recipe_revisions.recipe_id", "recipe_revisions.id"],
            name="fk_recipe_computed_owned_revision",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("recipe_revision_id", name="uq_recipe_computed_revision"),
    )
    op.create_index(
        op.f("ix_recipe_computed_nutrition_recipe_id"),
        "recipe_computed_nutrition",
        ["recipe_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        op.f("ix_recipe_computed_nutrition_recipe_id"),
        table_name="recipe_computed_nutrition",
    )
    op.drop_table("recipe_computed_nutrition")
    op.drop_index(
        op.f("ix_recipe_ingredient_foods_food_id"), table_name="recipe_ingredient_foods"
    )
    op.drop_index(
        op.f("ix_recipe_ingredient_foods_recipe_revision_id"),
        table_name="recipe_ingredient_foods",
    )
    op.drop_table("recipe_ingredient_foods")
    op.drop_constraint(
        "uq_recipe_ingredient_owner", "recipe_ingredients", type_="unique"
    )
