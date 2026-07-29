"""Canonical SQLAlchemy metadata for the hosted PostgreSQL schema."""

from __future__ import annotations

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    Column,
    DateTime,
    Float,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    LargeBinary,
    MetaData,
    PrimaryKeyConstraint,
    String,
    Table,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.sql import func


metadata = MetaData()

organizations = Table(
    "organizations",
    metadata,
    Column("organization_id", UUID(as_uuid=True), primary_key=True),
    Column("display_name", String(255), nullable=False),
    Column("created_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    Column("metadata", JSONB, nullable=False, server_default="{}"),
)

organization_members = Table(
    "organization_members",
    metadata,
    Column(
        "organization_id",
        UUID(as_uuid=True),
        ForeignKey("organizations.organization_id", ondelete="CASCADE"),
        nullable=False,
    ),
    Column("user_uid", String(255), nullable=False),
    Column("role", String(32), nullable=False),
    Column("joined_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    Column("metadata", JSONB, nullable=False, server_default="{}"),
    PrimaryKeyConstraint("organization_id", "user_uid"),
    CheckConstraint(
        "role IN ('viewer','operator','maintainer','admin')",
        name="ck_organization_members_role",
    ),
)
Index("ix_organization_members_user", organization_members.c.user_uid)

nodes = Table(
    "nodes",
    metadata,
    Column("node_id", String(255), primary_key=True),
    Column("display_name", String(255)),
    Column("created_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    Column("last_seen_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    Column("metadata", JSONB, nullable=False, server_default="{}"),
)

organization_nodes = Table(
    "organization_nodes",
    metadata,
    Column(
        "organization_id",
        UUID(as_uuid=True),
        ForeignKey("organizations.organization_id", ondelete="CASCADE"),
        nullable=False,
    ),
    Column(
        "node_id",
        String(255),
        ForeignKey("nodes.node_id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
    ),
    Column("assigned_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    Column("assigned_by", String(255), nullable=False),
    PrimaryKeyConstraint("organization_id", "node_id"),
)

vehicles = Table(
    "vehicles",
    metadata,
    Column("cloud_id", UUID(as_uuid=True), primary_key=True),
    Column("source_node_id", String(255), ForeignKey("nodes.node_id"), nullable=False),
    Column("local_id", BigInteger, nullable=False),
    Column("display_name", String(255), nullable=False),
    Column("class_name", String(100), nullable=False, server_default="unknown"),
    Column("last_track_id", BigInteger),
    Column("last_frame_index", BigInteger, nullable=False, server_default="0"),
    Column("last_seen_at", DateTime(timezone=True), nullable=False),
    Column("confidence", Float, nullable=False, server_default="0"),
    Column("bbox", JSONB, nullable=False, server_default="[]"),
    Column("center", JSONB, nullable=False, server_default="[]"),
    Column("metadata", JSONB, nullable=False, server_default="{}"),
    Column("created_at", DateTime(timezone=True), nullable=False),
    Column("updated_at", DateTime(timezone=True), nullable=False),
    UniqueConstraint("source_node_id", "local_id", name="uq_vehicles_node_local"),
    UniqueConstraint(
        "source_node_id",
        "local_id",
        "cloud_id",
        name="uq_vehicles_origin_cloud",
    ),
    CheckConstraint("local_id > 0", name="ck_vehicles_local_id_positive"),
    CheckConstraint("confidence >= 0 AND confidence <= 1", name="ck_vehicles_confidence"),
)
Index("ix_vehicles_updated_at", vehicles.c.updated_at.desc())

vehicle_id_mappings = Table(
    "vehicle_id_mappings",
    metadata,
    Column("node_id", String(255), nullable=False),
    Column("local_id", BigInteger, nullable=False),
    Column(
        "cloud_id",
        UUID(as_uuid=True),
        nullable=False,
        unique=True,
    ),
    Column("mapped_at", DateTime(timezone=True), nullable=False),
    ForeignKeyConstraint(
        ["node_id", "local_id", "cloud_id"],
        ["vehicles.source_node_id", "vehicles.local_id", "vehicles.cloud_id"],
        ondelete="CASCADE",
        name="fk_mapping_vehicle_origin",
    ),
    CheckConstraint("local_id > 0", name="ck_mapping_local_id_positive"),
)
vehicle_id_mappings.append_constraint(PrimaryKeyConstraint("node_id", "local_id"))

sessions = Table(
    "sessions",
    metadata,
    Column("session_id", String(255), primary_key=True),
    Column("node_id", String(255), ForeignKey("nodes.node_id"), nullable=False),
    Column("started_at", DateTime(timezone=True), nullable=False),
    Column("ended_at", DateTime(timezone=True)),
    Column("source_file", Text),
    Column("event_count", BigInteger, nullable=False, server_default="0"),
    Column("metadata", JSONB, nullable=False, server_default="{}"),
    UniqueConstraint("session_id", "node_id", name="uq_sessions_node"),
)
Index("ix_sessions_started_at", sessions.c.started_at.desc())

events = Table(
    "events",
    metadata,
    Column("event_id", UUID(as_uuid=True), primary_key=True),
    Column("session_id", String(255)),
    Column("source_node_id", String(255), ForeignKey("nodes.node_id"), nullable=False),
    Column("event_type", String(255), nullable=False),
    Column("occurred_at", DateTime(timezone=True), nullable=False),
    Column("severity", String(32), nullable=False, server_default="info"),
    Column("component", String(100), nullable=False, server_default="application"),
    Column("reason_code", String(255)),
    Column("schema_version", Integer, nullable=False),
    Column("correlation_id", String(255)),
    Column("data", JSONB, nullable=False, server_default="{}"),
    Column("received_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    ForeignKeyConstraint(
        ["session_id", "source_node_id"],
        ["sessions.session_id", "sessions.node_id"],
        name="fk_events_session_node",
    ),
    CheckConstraint("schema_version > 0", name="ck_events_schema_version"),
)
Index("ix_events_occurred_at", events.c.occurred_at.desc())
Index("ix_events_session_occurred", events.c.session_id, events.c.occurred_at.desc())

vehicle_features = Table(
    "vehicle_features",
    metadata,
    Column("feature_id", BigInteger, primary_key=True, autoincrement=True),
    Column(
        "vehicle_cloud_id",
        UUID(as_uuid=True),
        ForeignKey("vehicles.cloud_id", ondelete="CASCADE"),
        nullable=False,
    ),
    Column("source_feature_id", BigInteger),
    Column("gallery_type", String(32), nullable=False),
    Column("created_at", DateTime(timezone=True), nullable=False),
    Column("frame_index", BigInteger, nullable=False),
    Column("track_id", BigInteger),
    Column("bbox", JSONB, nullable=False),
    Column("quality_score", Float, nullable=False),
    Column("duplicate_score", Float),
    Column("embedding", JSONB, nullable=False),
    Column("crop_jpeg", LargeBinary),
    Column("metadata", JSONB, nullable=False, server_default="{}"),
    Column("provenance", JSONB, nullable=False),
    Column("is_active", Boolean, nullable=False, server_default="true"),
    Column("rolled_back_at", DateTime(timezone=True)),
    Column("rollback_reason", Text),
    UniqueConstraint(
        "vehicle_cloud_id",
        "source_feature_id",
        name="uq_vehicle_features_source",
    ),
    CheckConstraint(
        "gallery_type IN ('master','pending','candidate')",
        name="ck_vehicle_features_gallery_type",
    ),
)
Index(
    "ix_vehicle_features_vehicle_gallery",
    vehicle_features.c.vehicle_cloud_id,
    vehicle_features.c.gallery_type,
)

gallery_rollback_events = Table(
    "gallery_rollback_events",
    metadata,
    Column("rollback_id", BigInteger, primary_key=True, autoincrement=True),
    Column("source_node_id", String(255), ForeignKey("nodes.node_id"), nullable=False),
    Column("source_rollback_id", BigInteger, nullable=False),
    Column("created_at", DateTime(timezone=True), nullable=False),
    Column("actor", String(255), nullable=False),
    Column("reason", Text, nullable=False),
    Column("source_feature_ids", JSONB, nullable=False),
    UniqueConstraint(
        "source_node_id",
        "source_rollback_id",
        name="uq_gallery_rollback_source",
    ),
)

idempotency_keys = Table(
    "idempotency_keys",
    metadata,
    Column("idempotency_key", String(255), primary_key=True),
    Column("operation", String(255), nullable=False),
    Column("resource_id", String(255)),
    Column("response", JSONB, nullable=False, server_default="{}"),
    Column("created_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
)

audit_logs = Table(
    "audit_logs",
    metadata,
    Column("audit_id", UUID(as_uuid=True), primary_key=True),
    Column("request_id", String(255), nullable=False, unique=True),
    Column("actor_uid", String(255), nullable=False),
    Column("actor_roles", JSONB, nullable=False),
    Column("action", String(255), nullable=False),
    Column("resource_type", String(100), nullable=False),
    Column("resource_id", String(255), nullable=False),
    Column("source_ip", String(255)),
    Column("user_agent", Text),
    Column("before", JSONB, nullable=False),
    Column("after", JSONB, nullable=False),
    Column("metadata", JSONB, nullable=False, server_default="{}"),
    Column("occurred_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
)
Index("ix_audit_logs_resource", audit_logs.c.resource_type, audit_logs.c.resource_id)
Index("ix_audit_logs_actor_time", audit_logs.c.actor_uid, audit_logs.c.occurred_at.desc())

api_rate_limits = Table(
    "api_rate_limits",
    metadata,
    Column("subject", String(255), nullable=False),
    Column("route", String(255), nullable=False),
    Column("window_started_at", DateTime(timezone=True), nullable=False),
    Column("request_count", Integer, nullable=False),
    PrimaryKeyConstraint("subject", "route", "window_started_at"),
    CheckConstraint("request_count > 0", name="ck_api_rate_limit_positive"),
)
Index("ix_api_rate_limits_window", api_rate_limits.c.window_started_at)

registered_models = Table(
    "registered_models",
    metadata,
    Column("model_id", UUID(as_uuid=True), primary_key=True),
    Column(
        "organization_id",
        UUID(as_uuid=True),
        ForeignKey("organizations.organization_id", ondelete="CASCADE"),
        nullable=False,
    ),
    Column("name", String(255), nullable=False),
    Column("task", String(64), nullable=False),
    Column("description", Text),
    Column("created_by", String(255), nullable=False),
    Column("created_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    Column("metadata", JSONB, nullable=False, server_default="{}"),
    UniqueConstraint("organization_id", "name", name="uq_registered_models_org_name"),
    CheckConstraint(
        "task IN ('detection','reid','tracking','framing')",
        name="ck_registered_models_task",
    ),
)

model_versions = Table(
    "model_versions",
    metadata,
    Column("model_version_id", UUID(as_uuid=True), primary_key=True),
    Column(
        "model_id",
        UUID(as_uuid=True),
        ForeignKey("registered_models.model_id", ondelete="CASCADE"),
        nullable=False,
    ),
    Column("version", String(100), nullable=False),
    Column("artifact_uri", Text, nullable=False),
    Column("digest_sha256", String(64), nullable=False),
    Column("runtime", String(32), nullable=False),
    Column("status", String(32), nullable=False, server_default="candidate"),
    Column("metrics", JSONB, nullable=False, server_default="{}"),
    Column("created_by", String(255), nullable=False),
    Column("created_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    UniqueConstraint("model_id", "version", name="uq_model_versions_version"),
    CheckConstraint(
        "runtime IN ('onnx','tensorrt','pytorch','coreml')",
        name="ck_model_versions_runtime",
    ),
    CheckConstraint(
        "status IN ('candidate','validated','production','retired')",
        name="ck_model_versions_status",
    ),
)
Index("ix_model_versions_model_created", model_versions.c.model_id, model_versions.c.created_at.desc())

benchmark_jobs = Table(
    "benchmark_jobs",
    metadata,
    Column("job_id", UUID(as_uuid=True), primary_key=True),
    Column(
        "organization_id",
        UUID(as_uuid=True),
        ForeignKey("organizations.organization_id", ondelete="CASCADE"),
        nullable=False,
    ),
    Column(
        "model_version_id",
        UUID(as_uuid=True),
        ForeignKey("model_versions.model_version_id"),
        nullable=False,
    ),
    Column("created_by", String(255), nullable=False),
    Column("status", String(32), nullable=False, server_default="pending"),
    Column("accelerator", String(32), nullable=False),
    Column("dataset_uri", Text, nullable=False),
    Column("output_uri", Text, nullable=False),
    Column("execution_name", Text),
    Column("repetitions", Integer, nullable=False, server_default="1"),
    Column("submitted_event_id", UUID(as_uuid=True)),
    Column("result", JSONB, nullable=False, server_default="{}"),
    Column("error_message", Text),
    Column("created_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    Column("started_at", DateTime(timezone=True)),
    Column("finished_at", DateTime(timezone=True)),
    Column("metadata", JSONB, nullable=False, server_default="{}"),
    CheckConstraint(
        "status IN ('pending','submitted','running','succeeded','failed','cancelled')",
        name="ck_benchmark_jobs_status",
    ),
    CheckConstraint(
        "accelerator IN ('cpu','nvidia-l4')",
        name="ck_benchmark_jobs_accelerator",
    ),
    CheckConstraint("repetitions > 0 AND repetitions <= 20", name="ck_benchmark_repetitions"),
)
Index(
    "ix_benchmark_jobs_org_created",
    benchmark_jobs.c.organization_id,
    benchmark_jobs.c.created_at.desc(),
)

notification_channels = Table(
    "notification_channels",
    metadata,
    Column("channel_id", UUID(as_uuid=True), primary_key=True),
    Column(
        "organization_id",
        UUID(as_uuid=True),
        ForeignKey("organizations.organization_id", ondelete="CASCADE"),
        nullable=False,
    ),
    Column("channel_type", String(32), nullable=False),
    Column("display_name", String(255), nullable=False),
    Column("secret_ref", String(255), nullable=False),
    Column("enabled", Boolean, nullable=False, server_default="true"),
    Column("created_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    CheckConstraint(
        "channel_type IN ('email','webhook','firebase')",
        name="ck_notification_channels_type",
    ),
)

alert_rules = Table(
    "alert_rules",
    metadata,
    Column("rule_id", UUID(as_uuid=True), primary_key=True),
    Column(
        "organization_id",
        UUID(as_uuid=True),
        ForeignKey("organizations.organization_id", ondelete="CASCADE"),
        nullable=False,
    ),
    Column(
        "channel_id",
        UUID(as_uuid=True),
        ForeignKey("notification_channels.channel_id", ondelete="CASCADE"),
        nullable=False,
    ),
    Column("name", String(255), nullable=False),
    Column("event_type", String(255), nullable=False),
    Column("minimum_severity", String(16), nullable=False, server_default="warning"),
    Column("cooldown_seconds", Integer, nullable=False, server_default="300"),
    Column("enabled", Boolean, nullable=False, server_default="true"),
    Column("filters", JSONB, nullable=False, server_default="{}"),
    Column("created_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    CheckConstraint(
        "minimum_severity IN ('info','warning','error','critical')",
        name="ck_alert_rules_severity",
    ),
    CheckConstraint("cooldown_seconds >= 0", name="ck_alert_rules_cooldown"),
)

cloud_event_outbox = Table(
    "cloud_event_outbox",
    metadata,
    Column("event_id", UUID(as_uuid=True), primary_key=True),
    Column("organization_id", UUID(as_uuid=True), nullable=False),
    Column("topic", String(255), nullable=False),
    Column("event_type", String(255), nullable=False),
    Column("payload", JSONB, nullable=False),
    Column("publish_attempts", Integer, nullable=False, server_default="0"),
    Column("available_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    Column("published_at", DateTime(timezone=True)),
    Column("last_error", Text),
    Column("created_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    CheckConstraint("publish_attempts >= 0", name="ck_cloud_event_outbox_attempts"),
)
Index(
    "ix_cloud_event_outbox_pending",
    cloud_event_outbox.c.available_at,
    postgresql_where=cloud_event_outbox.c.published_at.is_(None),
)
