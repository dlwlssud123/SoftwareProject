"""Store only typed app usage metadata, separately from user records."""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "20261126_01"
down_revision = "20261125_01"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "usage_events",
        sa.Column("collector_key", sa.String(64), primary_key=True),
        sa.Column("event_id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        *[sa.Column(name, sa.String(size), nullable=False) for name, size in [("event", 32), ("feature", 24), ("action", 16), ("outcome", 16), ("app_version", 32), ("platform", 16)]],
        sa.Column("duration_ms", sa.Integer()),
        sa.Column("error_kind", sa.String(24)),
        sa.Column("request_id", postgresql.UUID(as_uuid=True)),
        sa.Column("result_count", sa.Integer()),
        sa.Column("result_kind", sa.String(24)),
        sa.Column("setting_kind", sa.String(16)),
        sa.Column("setting_value", sa.String(16)),
        sa.CheckConstraint("duration_ms IS NULL OR duration_ms BETWEEN 0 AND 3600000", name="ck_usage_duration"),
        sa.CheckConstraint("result_count IS NULL OR result_count BETWEEN 0 AND 1000000", name="ck_usage_count"),
    )
    op.create_index("ix_usage_created", "usage_events", ["created_at"])
    op.create_index("ix_usage_collector_created", "usage_events", ["collector_key", "created_at"])
    op.create_index("ix_usage_feature_created", "usage_events", ["feature", "created_at"])


def downgrade():
    op.drop_table("usage_events")
