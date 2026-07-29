"""Repeatable import from the edge SQLite/JSONL stores into PostgreSQL."""

from __future__ import annotations

import argparse
from contextlib import closing
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import sqlite3
from typing import Any, Iterator
from uuid import UUID, uuid5

from autocamtracker.cloud.contracts import EventEnvelope
from autocamtracker.cloud.postgres import PostgresCloudAdapter


IMPORT_NAMESPACE = UUID("66c58f3a-3826-4ef8-8d8e-524a5b03e727")


@dataclass(frozen=True, slots=True)
class ImportReport:
    vehicles: int = 0
    features: int = 0
    rollback_events: int = 0
    telemetry_events: int = 0


def deterministic_cloud_id(node_id: str, local_id: int) -> UUID:
    return uuid5(IMPORT_NAMESPACE, f"vehicle:{node_id}:{local_id}")


def _timestamp(value: int | float | None) -> datetime | None:
    if value is None:
        return None
    return datetime.fromtimestamp(float(value), tz=timezone.utc)


def _json(value: str | None, fallback: Any) -> Any:
    if not value:
        return fallback
    try:
        parsed = json.loads(value)
    except (TypeError, ValueError, json.JSONDecodeError):
        return fallback
    return parsed


class EdgeDataImporter:
    def __init__(self, adapter: PostgresCloudAdapter, node_id: str) -> None:
        if not node_id.strip():
            raise ValueError("node_id must not be empty")
        self.adapter = adapter
        self.node_id = node_id

    def import_sqlite(self, sqlite_path: Path) -> ImportReport:
        sqlite_path = Path(sqlite_path)
        if not sqlite_path.is_file():
            raise FileNotFoundError(sqlite_path)
        with closing(
            sqlite3.connect(sqlite_path.resolve().as_uri() + "?mode=ro", uri=True)
        ) as connection:
            connection.row_factory = sqlite3.Row
            connection.execute("PRAGMA query_only=ON")
            vehicle_count = self._vehicles(connection)
            feature_count = self._features(connection)
            rollback_count = self._rollbacks(connection)
        return ImportReport(vehicle_count, feature_count, rollback_count, 0)

    def import_telemetry(self, telemetry_dir: Path) -> int:
        imported = 0
        for path in sorted(Path(telemetry_dir).glob("autocamtracker-telemetry-*.jsonl")):
            for line_number, payload in self._jsonl(path):
                timestamp_ms = max(0, int(payload.get("timestamp_ms", 0)))
                event_id = uuid5(
                    IMPORT_NAMESPACE,
                    f"telemetry:{self.node_id}:{path.name}:{line_number}",
                )
                known = {
                    "schema_version",
                    "session_id",
                    "event",
                    "severity",
                    "component",
                    "reason_code",
                    "timestamp_ms",
                    "monotonic_s",
                }
                data = {
                    key: value
                    for key, value in payload.items()
                    if key not in known
                }
                data.update(
                    {
                        "session_id": str(payload.get("session_id", path.stem)),
                        "severity": str(payload.get("severity", "info")),
                        "component": str(payload.get("component", "application")),
                        "reason_code": payload.get("reason_code"),
                        "source_file": path.name,
                    }
                )
                self.adapter.publish(
                    EventEnvelope(
                        event_id=str(event_id),
                        event_type=str(payload.get("event", "unknown")),
                        occurred_at=_timestamp(timestamp_ms / 1000)
                        .isoformat()
                        .replace("+00:00", "Z"),
                        source_node_id=self.node_id,
                        schema_version=max(1, int(payload.get("schema_version", 1))),
                        data=data,
                    )
                )
                imported += 1
        return imported

    def _vehicles(self, connection: sqlite3.Connection) -> int:
        if not self._has_table(connection, "vehicles"):
            return 0
        rows = connection.execute("SELECT * FROM vehicles ORDER BY id").fetchall()
        for source in rows:
            row = dict(source)
            local_id = int(row["id"])
            self.adapter.import_vehicle(
                self.node_id,
                {
                    **row,
                    "created_at": _timestamp(row["created_at"]),
                    "updated_at": _timestamp(row["updated_at"]),
                    "last_seen_at": _timestamp(row["last_seen_timestamp"]),
                    "bbox": _json(row.get("bbox_json"), []),
                    "center": _json(row.get("center_json"), []),
                    "metadata": _json(row.get("metadata_json"), {}),
                },
                deterministic_cloud_id(self.node_id, local_id),
            )
        return len(rows)

    def _features(self, connection: sqlite3.Connection) -> int:
        if not self._has_table(connection, "vehicle_features"):
            return 0
        rows = connection.execute("SELECT * FROM vehicle_features ORDER BY id").fetchall()
        for source in rows:
            row = dict(source)
            self.adapter.import_feature(
                deterministic_cloud_id(self.node_id, int(row["vehicle_id"])),
                {
                    "source_feature_id": int(row["id"]),
                    "gallery_type": str(row["gallery_type"]),
                    "created_at": _timestamp(row["created_at"]),
                    "frame_index": int(row["frame_index"]),
                    "track_id": row.get("track_id"),
                    "bbox": _json(row.get("bbox_json"), []),
                    "quality_score": float(row["quality_score"]),
                    "duplicate_score": row.get("duplicate_score"),
                    "embedding": _json(row.get("embedding_json"), []),
                    "crop_jpeg": row.get("crop_jpeg"),
                    "metadata": _json(row.get("metadata_json"), {}),
                    "provenance": _json(row.get("provenance_json"), {}),
                    "is_active": bool(row.get("is_active", 1)),
                    "rolled_back_at": _timestamp(row.get("rolled_back_at")),
                    "rollback_reason": row.get("rollback_reason"),
                },
            )
        return len(rows)

    def _rollbacks(self, connection: sqlite3.Connection) -> int:
        if not self._has_table(connection, "gallery_rollback_events"):
            return 0
        rows = connection.execute(
            "SELECT * FROM gallery_rollback_events ORDER BY id"
        ).fetchall()
        for source in rows:
            row = dict(source)
            self.adapter.import_rollback(
                self.node_id,
                {
                    "source_rollback_id": int(row["id"]),
                    "created_at": _timestamp(row["created_at"]),
                    "actor": str(row["actor"]),
                    "reason": str(row["reason"]),
                    "source_feature_ids": _json(row.get("feature_ids_json"), []),
                },
            )
        return len(rows)

    @staticmethod
    def _has_table(connection: sqlite3.Connection, table: str) -> bool:
        return (
            connection.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
                (table,),
            ).fetchone()
            is not None
        )

    @staticmethod
    def _jsonl(path: Path) -> Iterator[tuple[int, dict[str, Any]]]:
        with path.open("r", encoding="utf-8") as handle:
            for line_number, line in enumerate(handle, start=1):
                try:
                    payload = json.loads(line)
                except (TypeError, ValueError, json.JSONDecodeError):
                    continue
                if isinstance(payload, dict):
                    yield line_number, payload


def main() -> None:
    parser = argparse.ArgumentParser(description="Import edge data into PostgreSQL")
    parser.add_argument("--sqlite", type=Path, default=Path("outputs/vehicle_identity.sqlite3"))
    parser.add_argument("--telemetry-dir", type=Path)
    parser.add_argument("--node-id", required=True)
    parser.add_argument("--database-url", default=os.environ.get("AIVD_DATABASE_URL"))
    parser.add_argument("--upgrade", action="store_true")
    args = parser.parse_args()
    if not args.database_url:
        parser.error("--database-url or AIVD_DATABASE_URL is required")
    if args.upgrade:
        from alembic import command
        from alembic.config import Config

        config = Config("alembic.ini")
        config.set_main_option("sqlalchemy.url", args.database_url)
        command.upgrade(config, "head")

    adapter = PostgresCloudAdapter(args.database_url)
    try:
        importer = EdgeDataImporter(adapter, args.node_id)
        report = importer.import_sqlite(args.sqlite)
        if args.telemetry_dir:
            report = ImportReport(
                vehicles=report.vehicles,
                features=report.features,
                rollback_events=report.rollback_events,
                telemetry_events=importer.import_telemetry(args.telemetry_dir),
            )
        print(json.dumps(asdict(report), separators=(",", ":")))
    finally:
        adapter.close()
