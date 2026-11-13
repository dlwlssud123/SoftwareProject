"""Allow gram_status 'unit_weight' for recipe ingredient mappings.

A count unit (e.g. 달걀 1개) is converted with a sourced per-unit weight from
agetech_data resources/unit_weights.json (식약처 노인 영양지수 교육자료, 한국인 영양소 섭취기준).

Revision ID: 20261113_01
Revises: 20261111_02
"""

from alembic import op

revision = "20261113_01"
down_revision = "20261111_02"
branch_labels = None
depends_on = None

BEFORE = (
    "direct",
    "direct_paren",
    "approx_ml",
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
    # Rows converted with a unit weight cannot satisfy the old list; mark them unconverted again.
    op.execute(
        "UPDATE recipe_ingredient_foods SET gram_status = 'count_unit', grams = NULL, "
        "contribution = NULL WHERE gram_status = 'unit_weight'"
    )
    _replace(BEFORE)
