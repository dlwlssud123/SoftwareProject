"""Create public recipe and food source tables

Revision ID: 20261105_01
Revises:
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "20261105_01"
down_revision: str | Sequence[str] | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "data_import_runs",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("fingerprint", sa.String(length=64), nullable=False),
        sa.Column("parser_version", sa.String(length=64), nullable=False),
        sa.Column("inputs", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("counts", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column(
            "completed_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("fingerprint"),
    )
    op.create_table(
        "foods",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("provider", sa.String(length=64), nullable=False),
        sa.Column("food_code", sa.String(length=128), nullable=False),
        sa.Column("active_revision_id", sa.Uuid(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("provider", "food_code", name="uq_foods_source"),
    )
    op.create_table(
        "recipes",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("provider", sa.String(length=64), nullable=False),
        sa.Column("source_id", sa.String(length=64), nullable=False),
        sa.Column("active_revision_id", sa.Uuid(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("provider", "source_id", name="uq_recipes_source"),
    )
    op.create_table(
        "food_revisions",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("food_id", sa.Uuid(), nullable=False),
        sa.Column("import_run_id", sa.Uuid(), nullable=False),
        sa.Column("fingerprint", sa.String(length=64), nullable=False),
        sa.Column("raw_sha256", sa.String(length=64), nullable=False),
        sa.Column("raw", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column(
            "normalized", postgresql.JSONB(astext_type=sa.Text()), nullable=False
        ),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("basis_text", sa.Text(), nullable=True),
        sa.Column("basis_amount", sa.Numeric(), nullable=True),
        sa.Column("basis_unit", sa.String(length=8), nullable=True),
        sa.Column("nutrients", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column(
            "quality_flags", postgresql.JSONB(astext_type=sa.Text()), nullable=False
        ),
        sa.Column("energy_kcal", sa.Numeric(), nullable=True),
        sa.Column("carbohydrate_g", sa.Numeric(), nullable=True),
        sa.Column("protein_g", sa.Numeric(), nullable=True),
        sa.Column("fat_g", sa.Numeric(), nullable=True),
        sa.Column("sugars_g", sa.Numeric(), nullable=True),
        sa.Column("fiber_g", sa.Numeric(), nullable=True),
        sa.Column("sodium_mg", sa.Numeric(), nullable=True),
        sa.CheckConstraint(
            "basis_unit IS NULL OR basis_unit IN ('g', 'mL')", name="ck_food_basis_unit"
        ),
        sa.CheckConstraint(
            "basis_amount IS NULL OR basis_amount > 0", name="ck_food_positive_basis"
        ),
        sa.ForeignKeyConstraint(
            ["food_id"],
            ["foods.id"],
        ),
        sa.ForeignKeyConstraint(
            ["import_run_id"],
            ["data_import_runs.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "food_id", "fingerprint", name="uq_food_revision_fingerprint"
        ),
        sa.UniqueConstraint("food_id", "id", name="uq_food_revision_owner"),
    )
    op.create_index(
        op.f("ix_food_revisions_food_id"), "food_revisions", ["food_id"], unique=False
    )
    op.create_table(
        "recipe_revisions",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("recipe_id", sa.Uuid(), nullable=False),
        sa.Column("import_run_id", sa.Uuid(), nullable=False),
        sa.Column("fingerprint", sa.String(length=64), nullable=False),
        sa.Column("raw_sha256", sa.String(length=64), nullable=False),
        sa.Column("effective_sha256", sa.String(length=64), nullable=False),
        sa.Column("raw", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("effective", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column(
            "corrections", postgresql.JSONB(astext_type=sa.Text()), nullable=False
        ),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("method", sa.Text(), nullable=True),
        sa.Column("category", sa.Text(), nullable=True),
        sa.Column("quality_status", sa.String(length=16), nullable=False),
        sa.Column("issues", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column(
            "missing_step_nos", postgresql.JSONB(astext_type=sa.Text()), nullable=False
        ),
        sa.Column("nutrition_basis", sa.String(length=64), nullable=False),
        sa.Column("source_weight_text", sa.Text(), nullable=True),
        sa.Column("source_energy_kcal", sa.Numeric(), nullable=True),
        sa.Column("source_carbohydrate_g", sa.Numeric(), nullable=True),
        sa.Column("source_protein_g", sa.Numeric(), nullable=True),
        sa.Column("source_fat_g", sa.Numeric(), nullable=True),
        sa.Column("source_sodium_mg", sa.Numeric(), nullable=True),
        sa.CheckConstraint(
            "quality_status IN ('ok', 'flagged', 'hold')", name="ck_recipe_quality"
        ),
        sa.ForeignKeyConstraint(
            ["import_run_id"],
            ["data_import_runs.id"],
        ),
        sa.ForeignKeyConstraint(
            ["recipe_id"],
            ["recipes.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "recipe_id", "fingerprint", name="uq_recipe_revision_fingerprint"
        ),
        sa.UniqueConstraint("recipe_id", "id", name="uq_recipe_revision_owner"),
    )
    op.create_index(
        op.f("ix_recipe_revisions_recipe_id"),
        "recipe_revisions",
        ["recipe_id"],
        unique=False,
    )
    op.create_table(
        "recipe_ingredients",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("recipe_revision_id", sa.Uuid(), nullable=False),
        sa.Column("order_no", sa.Integer(), nullable=False),
        sa.Column("line_no", sa.Integer(), nullable=False),
        sa.Column("section", sa.Text(), nullable=False),
        sa.Column("raw_item", sa.Text(), nullable=False),
        sa.Column("name_raw", sa.Text(), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("amount_text", sa.Text(), nullable=False),
        sa.Column("unit", sa.String(length=32), nullable=True),
        sa.Column("parsed", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.ForeignKeyConstraint(
            ["recipe_revision_id"],
            ["recipe_revisions.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "recipe_revision_id", "order_no", name="uq_recipe_ingredient_order"
        ),
    )
    op.create_index(
        op.f("ix_recipe_ingredients_recipe_revision_id"),
        "recipe_ingredients",
        ["recipe_revision_id"],
        unique=False,
    )
    op.create_table(
        "recipe_steps",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("recipe_revision_id", sa.Uuid(), nullable=False),
        sa.Column("source_no", sa.Integer(), nullable=False),
        sa.Column("stated_no", sa.Integer(), nullable=True),
        sa.Column("source_field", sa.String(length=32), nullable=False),
        sa.Column("text_raw", sa.Text(), nullable=False),
        sa.Column("text_clean", sa.Text(), nullable=False),
        sa.Column("image_url", sa.Text(), nullable=True),
        sa.ForeignKeyConstraint(
            ["recipe_revision_id"],
            ["recipe_revisions.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "recipe_revision_id", "source_no", name="uq_recipe_step_number"
        ),
    )
    op.create_index(
        op.f("ix_recipe_steps_recipe_revision_id"),
        "recipe_steps",
        ["recipe_revision_id"],
        unique=False,
    )

    op.create_foreign_key(
        "fk_recipe_active_owned_revision",
        "recipes",
        "recipe_revisions",
        ["id", "active_revision_id"],
        ["recipe_id", "id"],
    )
    op.create_foreign_key(
        "fk_food_active_owned_revision",
        "foods",
        "food_revisions",
        ["id", "active_revision_id"],
        ["food_id", "id"],
    )


def downgrade() -> None:
    op.drop_constraint("fk_recipe_active_owned_revision", "recipes", type_="foreignkey")
    op.drop_constraint("fk_food_active_owned_revision", "foods", type_="foreignkey")
    op.drop_index(op.f("ix_recipe_steps_recipe_revision_id"), table_name="recipe_steps")
    op.drop_table("recipe_steps")
    op.drop_index(
        op.f("ix_recipe_ingredients_recipe_revision_id"),
        table_name="recipe_ingredients",
    )
    op.drop_table("recipe_ingredients")
    op.drop_index(op.f("ix_recipe_revisions_recipe_id"), table_name="recipe_revisions")
    op.drop_table("recipe_revisions")
    op.drop_index(op.f("ix_food_revisions_food_id"), table_name="food_revisions")
    op.drop_table("food_revisions")
    op.drop_table("recipes")
    op.drop_table("foods")
    op.drop_table("data_import_runs")
