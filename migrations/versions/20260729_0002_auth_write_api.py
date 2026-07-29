"""Add append-only audit and distributed rate-limit state.

Revision ID: 20260729_0002
Revises: 20260729_0001
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "20260729_0002"
down_revision = "20260729_0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "audit_logs",
        sa.Column("audit_id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("request_id", sa.String(255), nullable=False, unique=True),
        sa.Column("actor_uid", sa.String(255), nullable=False),
        sa.Column("actor_roles", postgresql.JSONB, nullable=False),
        sa.Column("action", sa.String(255), nullable=False),
        sa.Column("resource_type", sa.String(100), nullable=False),
        sa.Column("resource_id", sa.String(255), nullable=False),
        sa.Column("source_ip", sa.String(255)),
        sa.Column("user_agent", sa.Text),
        sa.Column("before", postgresql.JSONB, nullable=False),
        sa.Column("after", postgresql.JSONB, nullable=False),
        sa.Column("metadata", postgresql.JSONB, nullable=False, server_default="{}"),
        sa.Column(
            "occurred_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )
    op.create_index(
        "ix_audit_logs_resource",
        "audit_logs",
        ["resource_type", "resource_id"],
    )
    op.create_index(
        "ix_audit_logs_actor_time",
        "audit_logs",
        ["actor_uid", sa.text("occurred_at DESC")],
    )
    op.execute(
        """
        CREATE FUNCTION reject_audit_log_mutation()
        RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN
            RAISE EXCEPTION 'audit_logs is append-only';
        END;
        $$;
        """
    )
    op.execute(
        """
        CREATE TRIGGER trg_audit_logs_append_only
        BEFORE UPDATE OR DELETE ON audit_logs
        FOR EACH ROW EXECUTE FUNCTION reject_audit_log_mutation();
        """
    )
    op.create_table(
        "api_rate_limits",
        sa.Column("subject", sa.String(255), nullable=False),
        sa.Column("route", sa.String(255), nullable=False),
        sa.Column("window_started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("request_count", sa.Integer, nullable=False),
        sa.PrimaryKeyConstraint("subject", "route", "window_started_at"),
        sa.CheckConstraint("request_count > 0", name="ck_api_rate_limit_positive"),
    )
    op.create_index(
        "ix_api_rate_limits_window",
        "api_rate_limits",
        ["window_started_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_api_rate_limits_window", table_name="api_rate_limits")
    op.drop_table("api_rate_limits")
    op.execute("DROP TRIGGER trg_audit_logs_append_only ON audit_logs")
    op.execute("DROP FUNCTION reject_audit_log_mutation()")
    op.drop_index("ix_audit_logs_actor_time", table_name="audit_logs")
    op.drop_index("ix_audit_logs_resource", table_name="audit_logs")
    op.drop_table("audit_logs")
