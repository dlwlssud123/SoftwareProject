"""Add user records, reviewed content, and job storage.

Revision ID: 20261110_01
Revises: 20261109_01
"""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "20261110_01"
down_revision = "20261109_01"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "life_guides",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("slug", sa.String(length=128), nullable=False),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("steps", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("source_reference", sa.Text(), nullable=False),
        sa.Column("checked_on", sa.Date(), nullable=False),
        sa.Column("is_published", sa.Boolean(), server_default="false", nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("slug"),
    )
    op.create_table(
        "meal_facilities",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("sido", sa.String(length=64), nullable=False),
        sa.Column("sigungu", sa.String(length=64), nullable=False),
        sa.Column("address", sa.Text(), nullable=True),
        sa.Column("latitude", sa.Numeric(precision=8, scale=5), nullable=True),
        sa.Column("longitude", sa.Numeric(precision=8, scale=5), nullable=True),
        sa.Column("eligibility_text", sa.Text(), nullable=True),
        sa.Column("hours_text", sa.Text(), nullable=True),
        sa.Column("contact_text", sa.Text(), nullable=True),
        sa.Column("source_url", sa.Text(), nullable=False),
        sa.Column("checked_on", sa.Date(), nullable=False),
        sa.Column("is_published", sa.Boolean(), server_default="false", nullable=False),
        sa.CheckConstraint(
            "(latitude IS NULL AND longitude IS NULL) OR (latitude IS NOT NULL AND longitude IS NOT NULL AND latitude BETWEEN -90 AND 90 AND longitude BETWEEN -180 AND 180)",
            name="ck_meal_facility_coordinates",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_meal_facilities_region",
        "meal_facilities",
        ["sido", "sigungu"],
        unique=False,
    )
    op.create_table(
        "seasonal_ingredients",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("month", sa.Integer(), nullable=False),
        sa.Column("ingredient_name", sa.String(length=128), nullable=False),
        sa.Column("recipe_ingredient_name", sa.Text(), nullable=False),
        sa.Column("source_url", sa.Text(), nullable=False),
        sa.Column("checked_on", sa.Date(), nullable=False),
        sa.Column("is_published", sa.Boolean(), server_default="false", nullable=False),
        sa.CheckConstraint("month BETWEEN 1 AND 12", name="ck_seasonal_month"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "month", "recipe_ingredient_name", name="uq_seasonal_month_recipe_name"
        ),
    )
    op.create_table(
        "job_runs",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=True),
        sa.Column("kind", sa.String(length=64), nullable=False),
        sa.Column(
            "status", sa.String(length=16), server_default="queued", nullable=False
        ),
        sa.Column("attempts", sa.Integer(), server_default="0", nullable=False),
        sa.Column(
            "next_run_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("error_code", sa.String(length=64), nullable=True),
        sa.CheckConstraint(
            "status IN ('queued', 'running', 'succeeded', 'failed', 'cancelled')",
            name="ck_job_run_status",
        ),
        sa.CheckConstraint("attempts >= 0", name="ck_job_run_attempts"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_job_runs_status_next_run",
        "job_runs",
        ["status", "next_run_at"],
        unique=False,
    )
    op.create_index(op.f("ix_job_runs_user_id"), "job_runs", ["user_id"], unique=False)
    op.create_table(
        "meal_logs",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("eaten_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_meal_logs_user_eaten", "meal_logs", ["user_id", "eaten_at"], unique=False
    )
    op.create_table(
        "saved_recipes",
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("recipe_id", sa.Uuid(), nullable=False),
        sa.Column(
            "saved_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["recipe_id"],
            ["recipes.id"],
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("user_id", "recipe_id"),
    )
    op.create_table(
        "meal_log_items",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("meal_log_id", sa.Uuid(), nullable=False),
        sa.Column("food_revision_id", sa.Uuid(), nullable=False),
        sa.Column("amount", sa.Numeric(precision=10, scale=3), nullable=False),
        sa.Column("amount_unit", sa.String(length=2), nullable=False),
        sa.Column("nutrients", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("calculation_version", sa.String(length=64), nullable=False),
        sa.CheckConstraint(
            "amount > 0 AND amount <> 'NaN'", name="ck_meal_log_item_portion"
        ),
        sa.CheckConstraint("amount_unit IN ('g', 'mL')", name="ck_meal_log_item_unit"),
        sa.ForeignKeyConstraint(
            ["food_revision_id"],
            ["food_revisions.id"],
        ),
        sa.ForeignKeyConstraint(["meal_log_id"], ["meal_logs.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_meal_log_items_meal_log_id"),
        "meal_log_items",
        ["meal_log_id"],
        unique=False,
    )
    op.create_table(
        "meal_plan_entries",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("plan_date", sa.Date(), nullable=False),
        sa.Column("meal_slot", sa.String(length=16), nullable=False),
        sa.Column("recipe_revision_id", sa.Uuid(), nullable=False),
        sa.CheckConstraint(
            "meal_slot IN ('breakfast', 'lunch', 'dinner', 'snack', 'special')",
            name="ck_meal_plan_slot",
        ),
        sa.ForeignKeyConstraint(
            ["recipe_revision_id"],
            ["recipe_revisions.id"],
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "user_id", "plan_date", "meal_slot", name="uq_meal_plan_user_date_slot"
        ),
    )
    op.create_table(
        "saved_welfare_services",
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("service_id", sa.Uuid(), nullable=False),
        sa.Column(
            "saved_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["service_id"],
            ["welfare_services.id"],
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("user_id", "service_id"),
    )
    op.drop_constraint(op.f("profiles_user_id_fkey"), "profiles", type_="foreignkey")
    op.create_foreign_key(
        "profiles_user_id_fkey",
        "profiles",
        "users",
        ["user_id"],
        ["id"],
        ondelete="CASCADE",
    )
    op.drop_constraint(op.f("sessions_user_id_fkey"), "sessions", type_="foreignkey")
    op.create_foreign_key(
        "sessions_user_id_fkey",
        "sessions",
        "users",
        ["user_id"],
        ["id"],
        ondelete="CASCADE",
    )


def downgrade() -> None:
    op.drop_constraint("sessions_user_id_fkey", "sessions", type_="foreignkey")
    op.create_foreign_key(
        op.f("sessions_user_id_fkey"), "sessions", "users", ["user_id"], ["id"]
    )
    op.drop_constraint("profiles_user_id_fkey", "profiles", type_="foreignkey")
    op.create_foreign_key(
        op.f("profiles_user_id_fkey"), "profiles", "users", ["user_id"], ["id"]
    )
    op.drop_table("saved_welfare_services")
    op.drop_table("meal_plan_entries")
    op.drop_index(op.f("ix_meal_log_items_meal_log_id"), table_name="meal_log_items")
    op.drop_table("meal_log_items")
    op.drop_table("saved_recipes")
    op.drop_index("ix_meal_logs_user_eaten", table_name="meal_logs")
    op.drop_table("meal_logs")
    op.drop_index(op.f("ix_job_runs_user_id"), table_name="job_runs")
    op.drop_index("ix_job_runs_status_next_run", table_name="job_runs")
    op.drop_table("job_runs")
    op.drop_table("seasonal_ingredients")
    op.drop_index("ix_meal_facilities_region", table_name="meal_facilities")
    op.drop_table("meal_facilities")
    op.drop_table("life_guides")
