"""Add offline-provisioned admin credentials and bounded login attempts."""

import sqlalchemy as sa
from alembic import op

revision = "20261120_04"
down_revision = "20261120_03"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "sessions",
        sa.Column("reauthenticate_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_check_constraint(
        "ck_session_reauthentication",
        "sessions",
        "reauthenticate_at IS NULL OR expires_at <= reauthenticate_at",
    )
    op.create_table(
        "admin_credentials",
        sa.Column("username", sa.String(64), primary_key=True),
        sa.Column(
            "user_id",
            sa.Uuid(),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
            unique=True,
        ),
        sa.Column("password_hash", sa.String(256), nullable=False),
        sa.Column("enabled", sa.Boolean(), server_default="true", nullable=False),
        sa.Column("failed_attempts", sa.Integer(), server_default="0", nullable=False),
        sa.Column("locked_until", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.CheckConstraint("failed_attempts >= 0", name="ck_admin_failed_attempts"),
    )
    op.create_table(
        "admin_login_buckets",
        sa.Column("bucket_key", sa.String(64), primary_key=True),
        sa.Column("window_start", sa.DateTime(timezone=True), nullable=False),
        sa.Column("attempts", sa.Integer(), nullable=False),
        sa.CheckConstraint("attempts >= 0", name="ck_admin_login_attempts"),
    )
    op.create_index(
        "ix_admin_login_buckets_window_start", "admin_login_buckets", ["window_start"]
    )


def downgrade() -> None:
    op.drop_table("admin_login_buckets")
    op.drop_table("admin_credentials")
    op.drop_constraint("ck_session_reauthentication", "sessions", type_="check")
    op.drop_column("sessions", "reauthenticate_at")
