"""Create the V3 hosted data model.

Revision ID: 20260729_0001
Revises:
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "20260729_0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "nodes",
        sa.Column("node_id", sa.String(255), primary_key=True),
        sa.Column("display_name", sa.String(255)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("metadata", postgresql.JSONB, nullable=False, server_default="{}"),
    )
    op.create_table(
        "vehicles",
        sa.Column("cloud_id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("source_node_id", sa.String(255), sa.ForeignKey("nodes.node_id"), nullable=False),
        sa.Column("local_id", sa.BigInteger, nullable=False),
        sa.Column("display_name", sa.String(255), nullable=False),
        sa.Column("class_name", sa.String(100), nullable=False, server_default="unknown"),
        sa.Column("last_track_id", sa.BigInteger),
        sa.Column("last_frame_index", sa.BigInteger, nullable=False, server_default="0"),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("confidence", sa.Float, nullable=False, server_default="0"),
        sa.Column("bbox", postgresql.JSONB, nullable=False, server_default="[]"),
        sa.Column("center", postgresql.JSONB, nullable=False, server_default="[]"),
        sa.Column("metadata", postgresql.JSONB, nullable=False, server_default="{}"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("source_node_id", "local_id", name="uq_vehicles_node_local"),
        sa.UniqueConstraint(
            "source_node_id",
            "local_id",
            "cloud_id",
            name="uq_vehicles_origin_cloud",
        ),
        sa.CheckConstraint("local_id > 0", name="ck_vehicles_local_id_positive"),
        sa.CheckConstraint("confidence >= 0 AND confidence <= 1", name="ck_vehicles_confidence"),
    )
    op.create_index("ix_vehicles_updated_at", "vehicles", [sa.text("updated_at DESC")])
    op.create_table(
        "vehicle_id_mappings",
        sa.Column("node_id", sa.String(255), nullable=False),
        sa.Column("local_id", sa.BigInteger, nullable=False),
        sa.Column(
            "cloud_id",
            postgresql.UUID(as_uuid=True),
            nullable=False,
            unique=True,
        ),
        sa.Column("mapped_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("node_id", "local_id"),
        sa.ForeignKeyConstraint(
            ["node_id", "local_id", "cloud_id"],
            ["vehicles.source_node_id", "vehicles.local_id", "vehicles.cloud_id"],
            ondelete="CASCADE",
            name="fk_mapping_vehicle_origin",
        ),
        sa.CheckConstraint("local_id > 0", name="ck_mapping_local_id_positive"),
    )
    op.create_table(
        "sessions",
        sa.Column("session_id", sa.String(255), primary_key=True),
        sa.Column("node_id", sa.String(255), sa.ForeignKey("nodes.node_id"), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("ended_at", sa.DateTime(timezone=True)),
        sa.Column("source_file", sa.Text),
        sa.Column("event_count", sa.BigInteger, nullable=False, server_default="0"),
        sa.Column("metadata", postgresql.JSONB, nullable=False, server_default="{}"),
        sa.UniqueConstraint("session_id", "node_id", name="uq_sessions_node"),
    )
    op.create_index("ix_sessions_started_at", "sessions", [sa.text("started_at DESC")])
    op.create_table(
        "events",
        sa.Column("event_id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("session_id", sa.String(255)),
        sa.Column("source_node_id", sa.String(255), sa.ForeignKey("nodes.node_id"), nullable=False),
        sa.Column("event_type", sa.String(255), nullable=False),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("severity", sa.String(32), nullable=False, server_default="info"),
        sa.Column("component", sa.String(100), nullable=False, server_default="application"),
        sa.Column("reason_code", sa.String(255)),
        sa.Column("schema_version", sa.Integer, nullable=False),
        sa.Column("correlation_id", sa.String(255)),
        sa.Column("data", postgresql.JSONB, nullable=False, server_default="{}"),
        sa.Column("received_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(
            ["session_id", "source_node_id"],
            ["sessions.session_id", "sessions.node_id"],
            name="fk_events_session_node",
        ),
        sa.CheckConstraint("schema_version > 0", name="ck_events_schema_version"),
    )
    op.create_index("ix_events_occurred_at", "events", [sa.text("occurred_at DESC")])
    op.create_index(
        "ix_events_session_occurred",
        "events",
        ["session_id", sa.text("occurred_at DESC")],
    )
    op.create_table(
        "vehicle_features",
        sa.Column("feature_id", sa.BigInteger, primary_key=True, autoincrement=True),
        sa.Column(
            "vehicle_cloud_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("vehicles.cloud_id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("source_feature_id", sa.BigInteger),
        sa.Column("gallery_type", sa.String(32), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("frame_index", sa.BigInteger, nullable=False),
        sa.Column("track_id", sa.BigInteger),
        sa.Column("bbox", postgresql.JSONB, nullable=False),
        sa.Column("quality_score", sa.Float, nullable=False),
        sa.Column("duplicate_score", sa.Float),
        sa.Column("embedding", postgresql.JSONB, nullable=False),
        sa.Column("crop_jpeg", sa.LargeBinary),
        sa.Column("metadata", postgresql.JSONB, nullable=False, server_default="{}"),
        sa.Column("provenance", postgresql.JSONB, nullable=False),
        sa.Column("is_active", sa.Boolean, nullable=False, server_default=sa.true()),
        sa.Column("rolled_back_at", sa.DateTime(timezone=True)),
        sa.Column("rollback_reason", sa.Text),
        sa.UniqueConstraint("vehicle_cloud_id", "source_feature_id", name="uq_vehicle_features_source"),
        sa.CheckConstraint(
            "gallery_type IN ('master','pending','candidate')",
            name="ck_vehicle_features_gallery_type",
        ),
    )
    op.create_index(
        "ix_vehicle_features_vehicle_gallery",
        "vehicle_features",
        ["vehicle_cloud_id", "gallery_type"],
    )
    op.create_table(
        "gallery_rollback_events",
        sa.Column("rollback_id", sa.BigInteger, primary_key=True, autoincrement=True),
        sa.Column("source_node_id", sa.String(255), sa.ForeignKey("nodes.node_id"), nullable=False),
        sa.Column("source_rollback_id", sa.BigInteger, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("actor", sa.String(255), nullable=False),
        sa.Column("reason", sa.Text, nullable=False),
        sa.Column("source_feature_ids", postgresql.JSONB, nullable=False),
        sa.UniqueConstraint(
            "source_node_id",
            "source_rollback_id",
            name="uq_gallery_rollback_source",
        ),
    )
    op.create_table(
        "idempotency_keys",
        sa.Column("idempotency_key", sa.String(255), primary_key=True),
        sa.Column("operation", sa.String(255), nullable=False),
        sa.Column("resource_id", sa.String(255)),
        sa.Column("response", postgresql.JSONB, nullable=False, server_default="{}"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )


def downgrade() -> None:
    op.drop_table("idempotency_keys")
    op.drop_table("gallery_rollback_events")
    op.drop_index("ix_vehicle_features_vehicle_gallery", table_name="vehicle_features")
    op.drop_table("vehicle_features")
    op.drop_index("ix_events_session_occurred", table_name="events")
    op.drop_index("ix_events_occurred_at", table_name="events")
    op.drop_table("events")
    op.drop_index("ix_sessions_started_at", table_name="sessions")
    op.drop_table("sessions")
    op.drop_table("vehicle_id_mappings")
    op.drop_index("ix_vehicles_updated_at", table_name="vehicles")
    op.drop_table("vehicles")
    op.drop_table("nodes")
