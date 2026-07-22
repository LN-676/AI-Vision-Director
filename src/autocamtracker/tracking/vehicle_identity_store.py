"""Persistent metadata-only vehicle identity store for AI Vision Director V1.0."""

from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
import sqlite3
from threading import RLock
from time import time
from typing import Any

from autocamtracker.tracking.sqlite_worker import SQLiteConnectionProxy, SQLiteWorker
from autocamtracker.vision.detector import TrackedDetection


@dataclass
class StoredVehicleIdentity:
    vehicle_id: int
    display_name: str
    class_name: str
    last_track_id: int | None
    last_frame_index: int
    last_seen_timestamp: float
    confidence: float
    bbox: tuple[float, float, float, float]
    center: tuple[float, float]
    metadata: dict[str, Any]


@dataclass
class VehicleIdentitySummary:
    vehicle_id: int
    display_name: str
    class_name: str
    last_track_id: int | None
    last_frame_index: int
    confidence: float
    master_feature_count: int = 0
    pending_feature_count: int = 0
    candidate_feature_count: int = 0
    updated_at: float = 0.0


@dataclass
class IdentityStoreSummary:
    vehicle_count: int
    master_feature_count: int
    pending_feature_count: int
    candidate_feature_count: int
    vehicles: list[VehicleIdentitySummary]


class VehicleIdentityStore:
    """SQLite-backed store for GID, last bbox, and basic vehicle metadata.

    V1.3 intentionally keeps embeddings out of this class. ReID features live
    in FeatureGallery and are written only by explicit Add Feature actions.
    """

    def __init__(self, db_path: Path | str, commit_interval_seconds: float = 0.5) -> None:
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._database = SQLiteWorker(self.db_path, name="identity-database")
        self.connection = SQLiteConnectionProxy(self._database)
        self.commit_interval_seconds = max(0.0, float(commit_interval_seconds))
        self._last_commit_at = time()
        self._pending_updates: dict[int, tuple[Any, ...]] = {}
        self._pending_lock = RLock()
        self._ensure_schema()
        self._known_vehicle_ids = {
            int(row["id"])
            for row in self._database.execute("SELECT id FROM vehicles").fetchall()
        }

    def close(self) -> None:
        self.flush()
        self._database.close()

    def flush(self) -> None:
        with self._pending_lock:
            if not self._pending_updates:
                return
            updates = list(self._pending_updates.values())
            self._database.executemany(
                """UPDATE vehicles
                SET updated_at = ?, class_name = ?, last_track_id = ?, last_frame_index = ?,
                    last_seen_timestamp = ?, confidence = ?, bbox_json = ?, center_json = ?,
                    metadata_json = COALESCE(?, metadata_json)
                WHERE id = ?""",
                updates,
                commit=True,
            )
            self._last_commit_at = time()
            self._pending_updates.clear()

    def create_vehicle(self, detection: TrackedDetection, metadata: dict[str, Any] | None = None) -> int:
        now = time()
        payload = self._detection_payload(detection)
        cursor = self._database.execute(
            """
            INSERT INTO vehicles (
                created_at,
                updated_at,
                class_name,
                last_track_id,
                last_frame_index,
                last_seen_timestamp,
                confidence,
                bbox_json,
                center_json,
                metadata_json
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                now,
                now,
                detection.class_name,
                detection.track_id,
                detection.frame_index,
                detection.timestamp,
                detection.confidence,
                payload["bbox_json"],
                payload["center_json"],
                self._metadata_json(metadata),
            ),
            commit=True,
        )
        with self._pending_lock:
            self._last_commit_at = time()
            vehicle_id = int(cursor.lastrowid)
            self._known_vehicle_ids.add(vehicle_id)
        return vehicle_id

    def update_vehicle(
        self,
        vehicle_id: int,
        detection: TrackedDetection,
        metadata: dict[str, Any] | None = None,
    ) -> bool:
        payload = self._detection_payload(detection)
        with self._pending_lock:
            if vehicle_id not in self._known_vehicle_ids:
                return False
            self._pending_updates[vehicle_id] = (
                time(),
                detection.class_name,
                detection.track_id,
                detection.frame_index,
                detection.timestamp,
                detection.confidence,
                payload["bbox_json"],
                payload["center_json"],
                self._metadata_json(metadata),
                vehicle_id,
            )
        self._commit_if_due()
        return True

    def get_vehicle(self, vehicle_id: int) -> StoredVehicleIdentity | None:
        row = self._database.execute(
            """
            SELECT
                id,
                display_name,
                class_name,
                last_track_id,
                last_frame_index,
                last_seen_timestamp,
                confidence,
                bbox_json,
                center_json,
                metadata_json
            FROM vehicles
            WHERE id = ?
            """,
            (vehicle_id,),
        ).fetchone()
        if row is None:
            return None
        return StoredVehicleIdentity(
            vehicle_id=int(row["id"]),
            display_name=self._display_name(row),
            class_name=str(row["class_name"]),
            last_track_id=row["last_track_id"],
            last_frame_index=int(row["last_frame_index"]),
            last_seen_timestamp=float(row["last_seen_timestamp"]),
            confidence=float(row["confidence"]),
            bbox=self._bbox_from_json(row["bbox_json"]),
            center=self._center_from_json(row["center_json"]),
            metadata=self._metadata_from_json(row["metadata_json"] if "metadata_json" in row.keys() else None),
        )

    def display_label(self, vehicle_id: int) -> str:
        row = self._database.execute(
            "SELECT id, display_name FROM vehicles WHERE id = ?",
            (vehicle_id,),
        ).fetchone()
        if row is None:
            return str(vehicle_id)
        return self._display_name(row)

    def update_display_name(self, vehicle_id: int, display_name: str) -> bool:
        value = display_name.strip() or None
        cursor = self._database.execute(
            "UPDATE vehicles SET display_name = ?, updated_at = ? WHERE id = ?",
            (value, time(), vehicle_id),
            commit=True,
        )
        return cursor.rowcount > 0

    def delete_vehicle(self, vehicle_id: int) -> bool:
        with self._pending_lock:
            self._pending_updates.pop(vehicle_id, None)
        cursor = self._database.execute(
            "DELETE FROM vehicles WHERE id = ?",
            (vehicle_id,),
            commit=True,
        )
        deleted = cursor.rowcount > 0
        if deleted:
            with self._pending_lock:
                self._known_vehicle_ids.discard(vehicle_id)
        return deleted

    def clear_track_link(self, vehicle_id: int, track_id: int | None) -> bool:
        if track_id is None:
            return False
        with self._pending_lock:
            self._pending_updates.pop(vehicle_id, None)
        cursor = self._database.execute(
            "UPDATE vehicles SET last_track_id = NULL, updated_at = ? WHERE id = ? AND last_track_id = ?",
            (time(), vehicle_id, track_id),
            commit=True,
        )
        return cursor.rowcount > 0

    def _commit_if_due(self) -> None:
        with self._pending_lock:
            due = bool(self._pending_updates) and time() - self._last_commit_at >= self.commit_interval_seconds
        if due:
            self.flush()

    def summary(self, feature_counts: dict[int, dict[str, int]] | None = None, limit: int = 50) -> IdentityStoreSummary:
        feature_counts = feature_counts or {}
        total = self._database.execute("SELECT COUNT(*) AS vehicle_count FROM vehicles").fetchone()
        rows = self._database.execute(
            """
            SELECT
                id,
                display_name,
                class_name,
                last_track_id,
                last_frame_index,
                confidence,
                updated_at
            FROM vehicles
            ORDER BY updated_at DESC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()
        vehicles: list[VehicleIdentitySummary] = []
        for row in rows:
            counts = feature_counts.get(int(row["id"]), {})
            vehicles.append(
                VehicleIdentitySummary(
                    vehicle_id=int(row["id"]),
                    display_name=self._display_name(row),
                    class_name=str(row["class_name"]),
                    last_track_id=row["last_track_id"],
                    last_frame_index=int(row["last_frame_index"]),
                    confidence=float(row["confidence"]),
                    master_feature_count=int(counts.get("master", 0)),
                    pending_feature_count=int(counts.get("pending", 0)),
                    candidate_feature_count=int(counts.get("candidate", 0)),
                    updated_at=float(row["updated_at"]),
                )
            )
        return IdentityStoreSummary(
            vehicle_count=int(total["vehicle_count"] or 0),
            master_feature_count=sum(int(counts.get("master", 0)) for counts in feature_counts.values()),
            pending_feature_count=sum(int(counts.get("pending", 0)) for counts in feature_counts.values()),
            candidate_feature_count=sum(int(counts.get("candidate", 0)) for counts in feature_counts.values()),
            vehicles=vehicles,
        )

    def _ensure_schema(self) -> None:
        self._database.execute(
            """
            CREATE TABLE IF NOT EXISTS vehicles (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                display_name TEXT,
                created_at REAL NOT NULL,
                updated_at REAL NOT NULL,
                class_name TEXT NOT NULL,
                last_track_id INTEGER,
                last_frame_index INTEGER NOT NULL,
                last_seen_timestamp REAL NOT NULL,
                confidence REAL NOT NULL,
                bbox_json TEXT NOT NULL,
                center_json TEXT NOT NULL,
                metadata_json TEXT
            )
            """,
            commit=True,
        )
        self._ensure_column("vehicles", "display_name", "TEXT")
        self._ensure_column("vehicles", "metadata_json", "TEXT")
        self._database.execute("DROP TABLE IF EXISTS observations", commit=True)
        self._database.execute(
            "CREATE INDEX IF NOT EXISTS idx_vehicles_updated_at ON vehicles(updated_at)",
            commit=True,
        )

    @staticmethod
    def _detection_payload(detection: TrackedDetection) -> dict[str, str]:
        return {
            "bbox_json": json.dumps(list(detection.bbox)),
            "center_json": json.dumps(list(detection.center)),
        }

    @staticmethod
    def _metadata_json(metadata: dict[str, Any] | None) -> str | None:
        if metadata is None:
            return None
        return json.dumps(metadata, sort_keys=True)

    @staticmethod
    def _metadata_from_json(value: str | None) -> dict[str, Any]:
        if not value:
            return {}
        try:
            parsed = json.loads(value)
        except (TypeError, ValueError, json.JSONDecodeError):
            return {}
        return parsed if isinstance(parsed, dict) else {}

    @staticmethod
    def _bbox_from_json(value: str) -> tuple[float, float, float, float]:
        items = json.loads(value)
        return (float(items[0]), float(items[1]), float(items[2]), float(items[3]))

    @staticmethod
    def _center_from_json(value: str) -> tuple[float, float]:
        items = json.loads(value)
        return (float(items[0]), float(items[1]))

    @staticmethod
    def _display_name(row: sqlite3.Row) -> str:
        value = row["display_name"] if "display_name" in row.keys() else None
        return str(value).strip() if value else str(row["id"])

    def _ensure_column(self, table_name: str, column_name: str, column_type: str) -> None:
        rows = self._database.execute(f"PRAGMA table_info({table_name})").fetchall()
        if any(row["name"] == column_name for row in rows):
            return
        self._database.execute(
            f"ALTER TABLE {table_name} ADD COLUMN {column_name} {column_type}",
            commit=True,
        )
