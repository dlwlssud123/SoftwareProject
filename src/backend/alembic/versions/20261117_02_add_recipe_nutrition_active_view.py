"""One row per published recipe with the computed nutrition of its active revision, for the API.

recipe_computed_nutrition keeps a row for every recipe revision it computed (a meal plan may point at an
older revision), so reading "the nutrition shown now" needs the recipes.active_revision_id join and the
same hold filter the recipe API uses. This view does that once and lifts the five nutrients the app shows
out of the JSON so they can be filtered and sorted. agetech_data.nutrition.api.computed_nutrition_block
turns a row into the API block (food_nutrition_contract.md 3.4).

Revision ID: 20261117_02
Revises: 20261117_01
"""

from alembic import op

revision = "20261117_02"
down_revision = "20261117_01"
branch_labels = None
depends_on = None

# Frozen copy of the importer constant (app.jobs.import_public_data.RECIPE_PROVIDER).
RECIPE_PROVIDER = "foodsafetykorea:COOKRCP01"
SHOWN = ("energy_kcal", "carbohydrate_g", "protein_g", "fat_g", "sodium_mg")


def upgrade() -> None:
    nutrients = ",\n       ".join(
        f"(n.computed->>'{k}')::numeric AS {k}" for k in SHOWN
    )
    op.execute(
        f"""
CREATE VIEW recipe_nutrition_active AS
SELECT r.id AS recipe_id, r.source_id, v.id AS recipe_revision_id, v.name, v.quality_status,
       n.complete, n.items, n.items_used, n.grams_used_pct,
       {nutrients},
       n.sodium_mg_per_1000kcal, n.carbohydrate_energy_pct, n.protein_energy_pct, n.fat_energy_pct,
       n.computed, n.computed_missing, n.coverage, n.mapper_version, n.computed_at
  FROM recipes r
  JOIN recipe_revisions v ON v.id = r.active_revision_id AND v.recipe_id = r.id
  JOIN recipe_computed_nutrition n ON n.recipe_revision_id = v.id AND n.recipe_id = r.id
 WHERE r.provider = '{RECIPE_PROVIDER}' AND v.quality_status <> 'hold'"""
    )
    op.execute(
        "COMMENT ON VIEW recipe_nutrition_active IS 'Computed nutrition (whole ingredient list, not a "
        "serving) of each published recipe''s active revision; turn a row into the API block with "
        "agetech_data.nutrition.api.computed_nutrition_block'"
    )


def downgrade() -> None:
    op.execute("DROP VIEW recipe_nutrition_active")
