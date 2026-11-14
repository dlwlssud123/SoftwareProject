"""Allow match_status 'excluded' for recipe ingredient mappings.

An ingredient that is not eaten (a bay leaf or a medicinal root taken out after simmering) or that is
already counted elsewhere in the same recipe is marked in agetech_data resources/ingredient_food_map.json
with "exclude". It counts as zero like water and does not make the recipe incomplete.

Revision ID: 20261114_01
Revises: 20261113_01
"""

from alembic import op

revision = "20261114_01"
down_revision = "20261113_01"
branch_labels = None
depends_on = None

BEFORE = ("reviewed", "curated", "exact", "water", "candidate", "unmapped")
AFTER = ("reviewed", "curated", "exact", "water", "excluded", "candidate", "unmapped")


def _in(values: tuple[str, ...]) -> str:
    return "match_status IN ({})".format(", ".join(f"'{value}'" for value in values))


def _replace(values: tuple[str, ...]) -> None:
    op.drop_constraint(
        "ck_recipe_ingredient_match", "recipe_ingredient_foods", type_="check"
    )
    op.create_check_constraint(
        "ck_recipe_ingredient_match", "recipe_ingredient_foods", _in(values)
    )


def upgrade() -> None:
    _replace(AFTER)


def downgrade() -> None:
    # The old list has no 'excluded'; those rows go back to the earlier 'no mapping' decision.
    # Their recipe summaries no longer match the rows, so mark them stale: map_recipe_foods picks
    # recipes to recompute by mapping_sha256 and will rewrite them on its next --apply.
    op.execute(
        "UPDATE recipe_computed_nutrition SET mapping_sha256 = 'stale:20261114_01' "
        "WHERE recipe_revision_id IN (SELECT recipe_revision_id FROM recipe_ingredient_foods "
        "WHERE match_status = 'excluded')"
    )
    op.execute(
        "UPDATE recipe_ingredient_foods SET match_status = 'unmapped' "
        "WHERE match_status = 'excluded'"
    )
    _replace(BEFORE)
