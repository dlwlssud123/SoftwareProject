"""Store portion-free comparison values next to each recipe's computed nutrition.

The public recipes rarely say how many servings an ingredient list makes (62 of 1,156 state 'N인분'),
so recipe totals cannot be compared with each other. agetech_data.nutrition.build.nutrient_density
derives values that do not depend on the portion: sodium per 1,000 kcal and the share of energy from
carbohydrate, protein and fat (4·4·9 kcal/g over the DB energy). They are NULL when the recipe is not
completely computed or a food in it has no value for that nutrient, so a partial sum is never ranked.

Existing rows keep NULL until the next map_recipe_foods --apply: the mapping hash now covers these
values (mapper v6), so the next run recomputes every active recipe (the daily refresh does this).

Revision ID: 20261117_01
Revises: 20261115_01
"""

import sqlalchemy as sa

from alembic import op

revision = "20261117_01"
down_revision = "20261115_01"
branch_labels = None
depends_on = None

COLUMNS = (
    "sodium_mg_per_1000kcal",
    "carbohydrate_energy_pct",
    "protein_energy_pct",
    "fat_energy_pct",
)


def upgrade() -> None:
    for column in COLUMNS:
        op.add_column(
            "recipe_computed_nutrition", sa.Column(column, sa.Numeric(), nullable=True)
        )
        op.create_check_constraint(
            f"ck_recipe_computed_{column}",
            "recipe_computed_nutrition",
            f"{column} IS NULL OR {column} >= 0",
        )


def downgrade() -> None:
    for column in COLUMNS:
        op.drop_constraint(
            f"ck_recipe_computed_{column}", "recipe_computed_nutrition", type_="check"
        )
        op.drop_column("recipe_computed_nutrition", column)
    # Rows written by mapper v6 hash the dropped values; mark them stale so an older
    # map_recipe_foods --apply rewrites them instead of trusting the stored hash.
    op.execute(
        "UPDATE recipe_computed_nutrition SET mapping_sha256 = 'stale:20261117_01' "
        "WHERE mapper_version = 'recipe-food-map-v6'"
    )
