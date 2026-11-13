"""Allow gram_status 'estimated' for recipe ingredient mappings.

When no sourced weight exists, agetech_data estimates the grams and writes the basis next to the value
(resources/estimated_amounts.json: USDA FoodData Central and 한국보건산업진흥원 portion weights, the
recipe DB's own g distribution for '약간·적당량', frying-oil uptake from raw↔fried food pairs). The row is
counted in the recipe totals and shown as an estimate.

Revision ID: 20261114_02
Revises: 20261114_01
"""

from alembic import op

revision = "20261114_02"
down_revision = "20261114_01"
branch_labels = None
depends_on = None

BEFORE = (
    "direct",
    "direct_paren",
    "approx_ml",
    "unit_weight",
    "count_unit",
    "qualitative",
    "missing",
    "unparsed",
)
AFTER = (
    "direct",
    "direct_paren",
    "approx_ml",
    "unit_weight",
    "estimated",
    "count_unit",
    "qualitative",
    "missing",
    "unparsed",
)


def _in(values: tuple[str, ...]) -> str:
    return "gram_status IN ({})".format(", ".join(f"'{value}'" for value in values))


def _replace(values: tuple[str, ...]) -> None:
    op.drop_constraint(
        "ck_recipe_ingredient_grams", "recipe_ingredient_foods", type_="check"
    )
    op.create_check_constraint(
        "ck_recipe_ingredient_grams", "recipe_ingredient_foods", _in(values)
    )


def upgrade() -> None:
    _replace(AFTER)


def downgrade() -> None:
    # Estimated rows cannot satisfy the old list; mark them unconverted. Their recipe summaries then
    # no longer match the rows, so mark them stale: map_recipe_foods picks recipes to recompute by
    # mapping_sha256 and rewrites them (with the older rules) on its next --apply.
    op.execute(
        "UPDATE recipe_computed_nutrition SET mapping_sha256 = 'stale:20261114_02' "
        "WHERE recipe_revision_id IN (SELECT recipe_revision_id FROM recipe_ingredient_foods "
        "WHERE gram_status = 'estimated')"
    )
    op.execute(
        "UPDATE recipe_ingredient_foods SET gram_status = 'unparsed', grams = NULL, "
        "contribution = NULL WHERE gram_status = 'estimated'"
    )
    _replace(BEFORE)
