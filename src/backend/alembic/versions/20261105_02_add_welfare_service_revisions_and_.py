"""Add welfare service revisions and application notices

Revision ID: 20261105_02
Revises: 20261105_01
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "20261105_02"
down_revision: str | Sequence[str] | None = "20261105_01"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "welfare_services",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("provider", sa.String(length=64), nullable=False),
        sa.Column("source_id", sa.String(length=64), nullable=False),
        sa.Column("scope", sa.String(length=64), nullable=False),
        sa.Column("publication_status", sa.String(length=16), nullable=False),
        sa.Column("active_revision_id", sa.Uuid(), nullable=True),
        sa.Column("last_checked_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_detail_checked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_seen_run_id", sa.Uuid(), nullable=False),
        sa.Column("missing_scans", sa.Integer(), nullable=False),
        sa.CheckConstraint(
            "publication_status IN ('published', 'missing', 'withdrawn', 'hold')",
            name="ck_welfare_publication",
        ),
        sa.CheckConstraint("missing_scans >= 0", name="ck_welfare_missing_scans"),
        sa.ForeignKeyConstraint(
            ["last_seen_run_id"],
            ["data_import_runs.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("provider", "source_id", name="uq_welfare_service_source"),
    )
    op.create_index(
        op.f("ix_welfare_services_scope"), "welfare_services", ["scope"], unique=False
    )
    op.create_table(
        "welfare_revisions",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("service_id", sa.Uuid(), nullable=False),
        sa.Column("import_run_id", sa.Uuid(), nullable=False),
        sa.Column("fingerprint", sa.String(length=64), nullable=False),
        sa.Column("normalizer_version", sa.String(length=64), nullable=False),
        sa.Column("raw", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("raw_sha256", sa.String(length=64), nullable=False),
        sa.Column(
            "normalized", postgresql.JSONB(astext_type=sa.Text()), nullable=False
        ),
        sa.Column("content_sha256", sa.String(length=64), nullable=False),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("summary", sa.Text(), nullable=False),
        sa.Column("target_text", sa.Text(), nullable=False),
        sa.Column("selection_text", sa.Text(), nullable=False),
        sa.Column("benefit_text", sa.Text(), nullable=False),
        sa.Column(
            "application", postgresql.JSONB(astext_type=sa.Text()), nullable=False
        ),
        sa.Column("contacts", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("source_url", sa.Text(), nullable=False),
        sa.Column("criteria_year", sa.String(length=16), nullable=True),
        sa.Column("detail_state", sa.String(length=16), nullable=False),
        sa.Column("quality_status", sa.String(length=16), nullable=False),
        sa.Column("issues", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("application_status", sa.String(length=16), nullable=False),
        sa.CheckConstraint(
            "application_status = 'unknown'",
            name="ck_welfare_service_application_unknown",
        ),
        sa.CheckConstraint(
            "quality_status IN ('ok', 'flagged', 'hold')", name="ck_welfare_quality"
        ),
        sa.CheckConstraint(
            "detail_state IN ('ready', 'pending')", name="ck_welfare_detail_state"
        ),
        sa.ForeignKeyConstraint(
            ["import_run_id"],
            ["data_import_runs.id"],
        ),
        sa.ForeignKeyConstraint(
            ["service_id"],
            ["welfare_services.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "service_id", "fingerprint", name="uq_welfare_revision_fingerprint"
        ),
        sa.UniqueConstraint("service_id", "id", name="uq_welfare_revision_owner"),
    )
    op.create_index(
        op.f("ix_welfare_revisions_service_id"),
        "welfare_revisions",
        ["service_id"],
        unique=False,
    )
    op.create_table(
        "welfare_notices",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("service_id", sa.Uuid(), nullable=False),
        sa.Column("source_revision_id", sa.Uuid(), nullable=False),
        sa.Column("source_notice_id", sa.String(length=128), nullable=False),
        sa.Column("source_url", sa.Text(), nullable=False),
        sa.Column("period_text", sa.Text(), nullable=False),
        sa.Column("period_type", sa.String(length=16), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("starts_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("deadline_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("checked_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "(period_type = 'fixed' AND deadline_at IS NOT NULL) OR (period_type IN ('unknown', 'ongoing') AND starts_at IS NULL AND deadline_at IS NULL)",
            name="ck_welfare_notice_period_dates",
        ),
        sa.CheckConstraint(
            "period_type IN ('unknown', 'fixed', 'ongoing')",
            name="ck_welfare_notice_period",
        ),
        sa.CheckConstraint(
            "status <> 'open' OR period_type <> 'unknown'",
            name="ck_welfare_notice_open_verified",
        ),
        sa.CheckConstraint(
            "status IN ('unknown', 'scheduled', 'open', 'closed', 'withdrawn')",
            name="ck_welfare_notice_status",
        ),
        sa.CheckConstraint(
            "starts_at IS NULL OR starts_at < deadline_at",
            name="ck_welfare_notice_date_order",
        ),
        sa.ForeignKeyConstraint(
            ["service_id", "source_revision_id"],
            ["welfare_revisions.service_id", "welfare_revisions.id"],
            name="fk_welfare_notice_owned_revision",
        ),
        sa.ForeignKeyConstraint(
            ["service_id"],
            ["welfare_services.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "service_id", "source_notice_id", name="uq_welfare_notice_source"
        ),
    )
    op.create_index(
        op.f("ix_welfare_notices_deadline_at"),
        "welfare_notices",
        ["deadline_at"],
        unique=False,
    )
    op.create_index(
        op.f("ix_welfare_notices_service_id"),
        "welfare_notices",
        ["service_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_welfare_notices_status"), "welfare_notices", ["status"], unique=False
    )

    op.create_foreign_key(
        "fk_welfare_active_owned_revision",
        "welfare_services",
        "welfare_revisions",
        ["id", "active_revision_id"],
        ["service_id", "id"],
    )


def downgrade() -> None:
    op.drop_constraint(
        "fk_welfare_active_owned_revision", "welfare_services", type_="foreignkey"
    )
    op.drop_index(op.f("ix_welfare_notices_status"), table_name="welfare_notices")
    op.drop_index(op.f("ix_welfare_notices_service_id"), table_name="welfare_notices")
    op.drop_index(op.f("ix_welfare_notices_deadline_at"), table_name="welfare_notices")
    op.drop_table("welfare_notices")
    op.drop_index(
        op.f("ix_welfare_revisions_service_id"), table_name="welfare_revisions"
    )
    op.drop_table("welfare_revisions")
    op.drop_index(op.f("ix_welfare_services_scope"), table_name="welfare_services")
    op.drop_table("welfare_services")
