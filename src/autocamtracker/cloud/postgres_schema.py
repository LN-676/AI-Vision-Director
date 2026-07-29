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

nodes = Table(
    "nodes",
    metadata,
    Column("node_id", String(255), primary_key=True),
    Column("display_name", String(255)),
    Column("created_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    Column("last_seen_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    Column("metadata", JSONB, nullable=False, server_default="{}"),
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
