"""Add public-data provenance to meal facilities and seasonal ingredients.

Facilities get a source key, reference date and quality flags; seasonal items get a
detail table and recipe links. Manually entered rows keep every new source column NULL.

Revision ID: 20261111_01
Revises: 20261110_01
"""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "20261111_01"
down_revision = "20261110_01"
branch_labels = None
depends_on = None

FACILITY_SOURCE_COLUMNS = (
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


def upgrade() -> None:
    jsonb = postgresql.JSONB(astext_type=sa.Text())
    op.add_column(
        "meal_facilities", sa.Column("provider", sa.String(length=64), nullable=True)
    )
    op.add_column(
        "meal_facilities", sa.Column("source_id", sa.String(length=64), nullable=True)
    )
    op.add_column(
        "meal_facilities", sa.Column("reference_date", sa.Date(), nullable=True)
    )
    op.add_column(
        "meal_facilities",
        sa.Column(
            "quality_flags",
            jsonb,
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
    )
    op.add_column("meal_facilities", sa.Column("normalized", jsonb, nullable=True))
    op.add_column(
        "meal_facilities",
        sa.Column("content_sha256", sa.String(length=64), nullable=True),
    )
    op.add_column(
        "meal_facilities",
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "meal_facilities", sa.Column("last_seen_run_id", sa.Uuid(), nullable=True)
    )
    op.create_foreign_key(
        "fk_meal_facility_last_seen_run",
        "meal_facilities",
        "data_import_runs",
        ["last_seen_run_id"],
        ["id"],
    )
    op.create_unique_constraint(
        "uq_meal_facility_source", "meal_facilities", ["provider", "source_id"]
    )
    op.create_check_constraint(
        "ck_meal_facility_source_complete",
        "meal_facilities",
        _all_or_none(FACILITY_SOURCE_COLUMNS),
    )
    op.create_check_constraint(
        "ck_meal_facility_flags",
        "meal_facilities",
        "jsonb_typeof(quality_flags) = 'array'",
    )

    op.create_table(
        "seasonal_foods",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("provider", sa.String(length=64), nullable=False),
        sa.Column("source_id", sa.String(length=32), nullable=False),
        sa.Column("month", sa.Integer(), nullable=False),
        sa.Column("fdmt_sn", sa.String(length=32), nullable=False),
        sa.Column("name", sa.String(length=128), nullable=False),
        sa.Column("terms", jsonb, nullable=False),
        sa.Column("image_url", sa.Text(), nullable=True),
        sa.Column("detail", jsonb, nullable=False),
        sa.Column("detail_status", sa.String(length=16), nullable=False),
        sa.Column("official_related_recipes", jsonb, nullable=False),
        sa.Column("shopping_search_url", sa.Text(), nullable=False),
        sa.Column("source_url", sa.Text(), nullable=False),
        sa.Column("checked_on", sa.Date(), nullable=False),
        sa.Column("normalized", jsonb, nullable=False),
        sa.Column("content_sha256", sa.String(length=64), nullable=False),
        sa.Column("links_sha256", sa.String(length=64), nullable=False),
        sa.Column("is_published", sa.Boolean(), server_default="false", nullable=False),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_seen_run_id", sa.Uuid(), nullable=False),
        sa.CheckConstraint("month BETWEEN 1 AND 12", name="ck_seasonal_food_month"),
        sa.CheckConstraint(
            "detail_status IN ('ok', 'failed')", name="ck_seasonal_food_detail"
        ),
        sa.ForeignKeyConstraint(
            ["last_seen_run_id"],
            ["data_import_runs.id"],
            name="fk_seasonal_food_last_seen_run",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("id", "month", name="uq_seasonal_food_month"),
        sa.UniqueConstraint("provider", "source_id", name="uq_seasonal_food_source"),
    )

    op.add_column(
        "seasonal_ingredients",
        sa.Column("seasonal_food_id", sa.Uuid(), nullable=True),
    )
    op.add_column(
        "seasonal_ingredients", sa.Column("match_term", sa.Text(), nullable=True)
    )
    op.add_column(
        "seasonal_ingredients",
        sa.Column("match_kind", sa.String(length=16), nullable=True),
    )
    op.create_foreign_key(
        "fk_seasonal_ingredient_food_month",
        "seasonal_ingredients",
        "seasonal_foods",
        ["seasonal_food_id", "month"],
        ["id", "month"],
        ondelete="CASCADE",
    )
    op.create_check_constraint(
        "ck_seasonal_ingredient_match",
        "seasonal_ingredients",
        "(seasonal_food_id IS NULL AND match_term IS NULL AND match_kind IS NULL) OR "
        "(seasonal_food_id IS NOT NULL AND match_term IS NOT NULL "
        "AND match_kind IN ('official', 'alias'))",
    )
    op.create_index(
        op.f("ix_seasonal_ingredients_seasonal_food_id"),
        "seasonal_ingredients",
        ["seasonal_food_id"],
        unique=False,
    )

    op.create_table(
        "seasonal_recipe_links",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("seasonal_food_id", sa.Uuid(), nullable=False),
        sa.Column("recipe_id", sa.Uuid(), nullable=False),
        sa.Column("recipe_revision_id", sa.Uuid(), nullable=False),
        sa.Column("ingredient_names", jsonb, nullable=False),
        sa.Column("weight_g", sa.Numeric(), nullable=True),
        sa.Column("share", sa.Numeric(), nullable=True),
        sa.CheckConstraint(
            "share IS NULL OR (share >= 0 AND share <= 1)",
            name="ck_seasonal_link_share",
        ),
        sa.CheckConstraint(
            "(share IS NULL) = (weight_g IS NULL)", name="ck_seasonal_link_weight"
        ),
        sa.ForeignKeyConstraint(
            ["recipe_id", "recipe_revision_id"],
            ["recipe_revisions.recipe_id", "recipe_revisions.id"],
            name="fk_seasonal_link_owned_revision",
        ),
        sa.ForeignKeyConstraint(
            ["seasonal_food_id"],
            ["seasonal_foods.id"],
            name="fk_seasonal_link_food",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "seasonal_food_id", "recipe_id", name="uq_seasonal_recipe_link"
        ),
    )
    op.create_index(
        "ix_seasonal_recipe_links_recipe",
        "seasonal_recipe_links",
        ["recipe_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_seasonal_recipe_links_seasonal_food_id"),
        "seasonal_recipe_links",
        ["seasonal_food_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        op.f("ix_seasonal_recipe_links_seasonal_food_id"),
        table_name="seasonal_recipe_links",
    )
    op.drop_index("ix_seasonal_recipe_links_recipe", table_name="seasonal_recipe_links")
    op.drop_table("seasonal_recipe_links")
    op.drop_index(
        op.f("ix_seasonal_ingredients_seasonal_food_id"),
        table_name="seasonal_ingredients",
    )
    op.drop_constraint(
        "ck_seasonal_ingredient_match", "seasonal_ingredients", type_="check"
    )
    op.drop_constraint(
        "fk_seasonal_ingredient_food_month", "seasonal_ingredients", type_="foreignkey"
    )
    # Imported mappings depend on seasonal_foods; manual rows survive the downgrade.
    op.execute("DELETE FROM seasonal_ingredients WHERE seasonal_food_id IS NOT NULL")
    op.drop_column("seasonal_ingredients", "match_kind")
    op.drop_column("seasonal_ingredients", "match_term")
    op.drop_column("seasonal_ingredients", "seasonal_food_id")
    op.drop_table("seasonal_foods")

    # Without source keys a later re-import could not match these rows; keep manual rows only.
    op.execute("DELETE FROM meal_facilities WHERE provider IS NOT NULL")
    op.drop_constraint("ck_meal_facility_flags", "meal_facilities", type_="check")
    op.drop_constraint(
        "ck_meal_facility_source_complete", "meal_facilities", type_="check"
    )
    op.drop_constraint("uq_meal_facility_source", "meal_facilities", type_="unique")
    op.drop_constraint(
        "fk_meal_facility_last_seen_run", "meal_facilities", type_="foreignkey"
    )
    for column in (
        "last_seen_run_id",
        "last_seen_at",
        "content_sha256",
        "normalized",
        "quality_flags",
        "reference_date",
        "source_id",
        "provider",
    ):
        op.drop_column("meal_facilities", column)
