"""Add Phase 6 multi-tenant jobs, registry, alerts, and event outbox.

Revision ID: 20260729_0003
Revises: 20260729_0002
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "20260729_0003"
down_revision = "20260729_0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "organizations",
        sa.Column("organization_id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("display_name", sa.String(255), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("metadata", postgresql.JSONB, nullable=False, server_default="{}"),
    )
    op.create_table(
        "organization_members",
        sa.Column("organization_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("organizations.organization_id", ondelete="CASCADE"), nullable=False),
        sa.Column("user_uid", sa.String(255), nullable=False),
        sa.Column("role", sa.String(32), nullable=False),
        sa.Column("joined_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("metadata", postgresql.JSONB, nullable=False, server_default="{}"),
        sa.PrimaryKeyConstraint("organization_id", "user_uid"),
        sa.CheckConstraint("role IN ('viewer','operator','maintainer','admin')", name="ck_organization_members_role"),
    )
    op.create_index("ix_organization_members_user", "organization_members", ["user_uid"])
    op.create_table(
        "organization_nodes",
        sa.Column("organization_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("organizations.organization_id", ondelete="CASCADE"), nullable=False),
        sa.Column("node_id", sa.String(255), sa.ForeignKey("nodes.node_id", ondelete="CASCADE"), nullable=False, unique=True),
        sa.Column("assigned_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("assigned_by", sa.String(255), nullable=False),
        sa.PrimaryKeyConstraint("organization_id", "node_id"),
    )
    op.create_table(
        "registered_models",
        sa.Column("model_id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("organization_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("organizations.organization_id", ondelete="CASCADE"), nullable=False),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("task", sa.String(64), nullable=False),
        sa.Column("description", sa.Text),
        sa.Column("created_by", sa.String(255), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("metadata", postgresql.JSONB, nullable=False, server_default="{}"),
        sa.UniqueConstraint("organization_id", "name", name="uq_registered_models_org_name"),
        sa.CheckConstraint("task IN ('detection','reid','tracking','framing')", name="ck_registered_models_task"),
    )
    op.create_table(
        "model_versions",
        sa.Column("model_version_id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("model_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("registered_models.model_id", ondelete="CASCADE"), nullable=False),
        sa.Column("version", sa.String(100), nullable=False),
        sa.Column("artifact_uri", sa.Text, nullable=False),
        sa.Column("digest_sha256", sa.String(64), nullable=False),
        sa.Column("runtime", sa.String(32), nullable=False),
        sa.Column("status", sa.String(32), nullable=False, server_default="candidate"),
        sa.Column("metrics", postgresql.JSONB, nullable=False, server_default="{}"),
        sa.Column("created_by", sa.String(255), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("model_id", "version", name="uq_model_versions_version"),
        sa.CheckConstraint("runtime IN ('onnx','tensorrt','pytorch','coreml')", name="ck_model_versions_runtime"),
        sa.CheckConstraint("status IN ('candidate','validated','production','retired')", name="ck_model_versions_status"),
    )
    op.create_index("ix_model_versions_model_created", "model_versions", ["model_id", sa.text("created_at DESC")])
    op.create_table(
        "benchmark_jobs",
        sa.Column("job_id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("organization_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("organizations.organization_id", ondelete="CASCADE"), nullable=False),
        sa.Column("model_version_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("model_versions.model_version_id"), nullable=False),
        sa.Column("created_by", sa.String(255), nullable=False),
        sa.Column("status", sa.String(32), nullable=False, server_default="pending"),
        sa.Column("accelerator", sa.String(32), nullable=False),
        sa.Column("dataset_uri", sa.Text, nullable=False),
        sa.Column("output_uri", sa.Text, nullable=False),
        sa.Column("execution_name", sa.Text),
        sa.Column("repetitions", sa.Integer, nullable=False, server_default="1"),
        sa.Column("submitted_event_id", postgresql.UUID(as_uuid=True)),
        sa.Column("result", postgresql.JSONB, nullable=False, server_default="{}"),
        sa.Column("error_message", sa.Text),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("started_at", sa.DateTime(timezone=True)),
        sa.Column("finished_at", sa.DateTime(timezone=True)),
        sa.Column("metadata", postgresql.JSONB, nullable=False, server_default="{}"),
        sa.CheckConstraint("status IN ('pending','submitted','running','succeeded','failed','cancelled')", name="ck_benchmark_jobs_status"),
        sa.CheckConstraint("accelerator IN ('cpu','nvidia-l4')", name="ck_benchmark_jobs_accelerator"),
        sa.CheckConstraint("repetitions > 0 AND repetitions <= 20", name="ck_benchmark_repetitions"),
    )
    op.create_index("ix_benchmark_jobs_org_created", "benchmark_jobs", ["organization_id", sa.text("created_at DESC")])
    op.create_table(
        "notification_channels",
        sa.Column("channel_id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("organization_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("organizations.organization_id", ondelete="CASCADE"), nullable=False),
        sa.Column("channel_type", sa.String(32), nullable=False),
        sa.Column("display_name", sa.String(255), nullable=False),
        sa.Column("secret_ref", sa.String(255), nullable=False),
        sa.Column("enabled", sa.Boolean, nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint("channel_type IN ('email','webhook','firebase')", name="ck_notification_channels_type"),
    )
    op.create_table(
        "alert_rules",
        sa.Column("rule_id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("organization_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("organizations.organization_id", ondelete="CASCADE"), nullable=False),
        sa.Column("channel_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("notification_channels.channel_id", ondelete="CASCADE"), nullable=False),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("event_type", sa.String(255), nullable=False),
        sa.Column("minimum_severity", sa.String(16), nullable=False, server_default="warning"),
        sa.Column("cooldown_seconds", sa.Integer, nullable=False, server_default="300"),
        sa.Column("enabled", sa.Boolean, nullable=False, server_default=sa.true()),
        sa.Column("filters", postgresql.JSONB, nullable=False, server_default="{}"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint("minimum_severity IN ('info','warning','error','critical')", name="ck_alert_rules_severity"),
        sa.CheckConstraint("cooldown_seconds >= 0", name="ck_alert_rules_cooldown"),
    )
    op.create_table(
        "cloud_event_outbox",
        sa.Column("event_id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("organization_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("topic", sa.String(255), nullable=False),
        sa.Column("event_type", sa.String(255), nullable=False),
        sa.Column("payload", postgresql.JSONB, nullable=False),
        sa.Column("publish_attempts", sa.Integer, nullable=False, server_default="0"),
        sa.Column("available_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("published_at", sa.DateTime(timezone=True)),
        sa.Column("last_error", sa.Text),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint("publish_attempts >= 0", name="ck_cloud_event_outbox_attempts"),
    )
    op.create_index(
        "ix_cloud_event_outbox_pending",
        "cloud_event_outbox",
        ["available_at"],
        postgresql_where=sa.text("published_at IS NULL"),
    )


def downgrade() -> None:
    op.drop_index("ix_cloud_event_outbox_pending", table_name="cloud_event_outbox")
    op.drop_table("cloud_event_outbox")
    op.drop_table("alert_rules")
    op.drop_table("notification_channels")
    op.drop_index("ix_benchmark_jobs_org_created", table_name="benchmark_jobs")
    op.drop_table("benchmark_jobs")
    op.drop_index("ix_model_versions_model_created", table_name="model_versions")
    op.drop_table("model_versions")
    op.drop_table("registered_models")
    op.drop_table("organization_nodes")
    op.drop_index("ix_organization_members_user", table_name="organization_members")
    op.drop_table("organization_members")
    op.drop_table("organizations")
