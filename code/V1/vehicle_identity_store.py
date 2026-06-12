"""Persistent vehicle identity store for AutoCamTracker V1.

This module is intentionally lightweight: it gives the runtime a durable
vehicle_id layer before introducing heavier ReID embeddings or license plate
OCR. The stored color signature is not a strong identity by itself, but it is a
useful first matching signal when combined with class, box shape, and time.
"""

from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
import sqlite3
from time import time
from typing import Any

try:
    from video_detector import TrackedDetection
except ImportError:  # pragma: no cover
    from .video_detector import TrackedDetection


@dataclass
class IdentityStoreMatch:
    vehicle_id: int
    score: float


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
    color_signature: list[float] | None


@dataclass
class VehicleIdentitySummary:
    vehicle_id: int
    display_name: str
    class_name: str
    last_track_id: int | None
    last_frame_index: int
    confidence: float
    observation_count: int
    duplicate_observation_count: int
    updated_at: float


@dataclass
class IdentityStoreSummary:
    vehicle_count: int
    observation_count: int
    duplicate_observation_count: int
    vehicles: list[VehicleIdentitySummary]


class VehicleIdentityStore:
    """SQLite-backed store for long-lived vehicle identities and observations."""

    def __init__(self, db_path: Path | str) -> None:
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.connection = sqlite3.connect(self.db_path)
        self.connection.row_factory = sqlite3.Row
        self._ensure_schema()

    def close(self) -> None:
        self.connection.close()

    def create_vehicle(
        self,
        detection: TrackedDetection,
        color_signature: Any | None = None,
    ) -> int:
        now = time()
        payload = self._detection_payload(detection)
        cursor = self.connection.execute(
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
                color_signature_json,
                observation_count
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0)
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
                self._signature_json(color_signature),
            ),
        )
        vehicle_id = int(cursor.lastrowid)
        self.record_observation(vehicle_id, detection, color_signature)
        return vehicle_id

    def record_observation(
        self,
        vehicle_id: int,
        detection: TrackedDetection,
        color_signature: Any | None = None,
    ) -> None:
        payload = self._detection_payload(detection)
        signature_json = self._signature_json(color_signature)
        self.connection.execute(
            """
            INSERT INTO observations (
                vehicle_id,
                seen_at,
                track_id,
                frame_index,
                seen_timestamp,
                class_name,
                confidence,
                bbox_json,
                center_json,
                tracker_name,
                color_signature_json
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                vehicle_id,
                time(),
                detection.track_id,
                detection.frame_index,
                detection.timestamp,
                detection.class_name,
                detection.confidence,
                payload["bbox_json"],
                payload["center_json"],
                detection.tracker_name,
                signature_json,
            ),
        )
        self.connection.execute(
            """
            UPDATE vehicles
            SET updated_at = ?,
                class_name = ?,
                last_track_id = ?,
                last_frame_index = ?,
                last_seen_timestamp = ?,
                confidence = ?,
                bbox_json = ?,
                center_json = ?,
                color_signature_json = COALESCE(?, color_signature_json),
                observation_count = observation_count + 1
            WHERE id = ?
            """,
            (
                time(),
                detection.class_name,
                detection.track_id,
                detection.frame_index,
                detection.timestamp,
                detection.confidence,
                payload["bbox_json"],
                payload["center_json"],
                signature_json,
                vehicle_id,
            ),
        )
        self.connection.commit()

    def find_best_match(
        self,
        detection: TrackedDetection,
        color_signature: Any | None = None,
        min_score: float = 0.72,
    ) -> IdentityStoreMatch | None:
        rows = self.connection.execute(
            """
            SELECT id, class_name, bbox_json, color_signature_json, observation_count
            FROM vehicles
            WHERE color_signature_json IS NOT NULL
            ORDER BY updated_at DESC
            LIMIT 200
            """
        ).fetchall()

        best: IdentityStoreMatch | None = None
        for row in rows:
            score = self._match_score(row, detection, color_signature)
            if best is None or score > best.score:
                best = IdentityStoreMatch(vehicle_id=int(row["id"]), score=score)

        if best is None or best.score < min_score:
            return None
        return best

    def get_vehicle(self, vehicle_id: int) -> StoredVehicleIdentity | None:
        row = self.connection.execute(
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
                color_signature_json
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
            color_signature=self._signature_from_json(row["color_signature_json"]),
        )

    def score_vehicle_match(
        self,
        vehicle_id: int,
        detection: TrackedDetection,
        color_signature: Any | None = None,
    ) -> float | None:
        row = self.connection.execute(
            """
            SELECT id, class_name, bbox_json, color_signature_json, observation_count
            FROM vehicles
            WHERE id = ?
            """,
            (vehicle_id,),
        ).fetchone()
        if row is None:
            return None
        return self._match_score(row, detection, color_signature)

    def display_label(self, vehicle_id: int) -> str:
        row = self.connection.execute(
            "SELECT id, display_name FROM vehicles WHERE id = ?",
            (vehicle_id,),
        ).fetchone()
        if row is None:
            return str(vehicle_id)
        return self._display_name(row)

    def update_display_name(self, vehicle_id: int, display_name: str) -> bool:
        value = display_name.strip() or None
        cursor = self.connection.execute(
            "UPDATE vehicles SET display_name = ?, updated_at = ? WHERE id = ?",
            (value, time(), vehicle_id),
        )
        self.connection.commit()
        return cursor.rowcount > 0

    def delete_vehicle(self, vehicle_id: int) -> bool:
        cursor = self.connection.execute("DELETE FROM observations WHERE vehicle_id = ?", (vehicle_id,))
        observation_count = cursor.rowcount
        cursor = self.connection.execute("DELETE FROM vehicles WHERE id = ?", (vehicle_id,))
        vehicle_deleted = cursor.rowcount > 0
        self.connection.commit()
        return vehicle_deleted or observation_count > 0

    def summary(self, limit: int = 50) -> IdentityStoreSummary:
        total = self.connection.execute(
            """
            SELECT
                COUNT(*) AS vehicle_count,
                COALESCE(SUM(observation_count), 0) AS observation_count,
                COALESCE(SUM(MAX(observation_count - 1, 0)), 0) AS duplicate_observation_count
            FROM vehicles
            """
        ).fetchone()
        rows = self.connection.execute(
            """
            SELECT
                id,
                display_name,
                class_name,
                last_track_id,
                last_frame_index,
                confidence,
                observation_count,
                updated_at
            FROM vehicles
            ORDER BY updated_at DESC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()
        vehicles = [
            VehicleIdentitySummary(
                vehicle_id=int(row["id"]),
                display_name=self._display_name(row),
                class_name=str(row["class_name"]),
                last_track_id=row["last_track_id"],
                last_frame_index=int(row["last_frame_index"]),
                confidence=float(row["confidence"]),
                observation_count=int(row["observation_count"]),
                duplicate_observation_count=max(0, int(row["observation_count"]) - 1),
                updated_at=float(row["updated_at"]),
            )
            for row in rows
        ]
        return IdentityStoreSummary(
            vehicle_count=int(total["vehicle_count"] or 0),
            observation_count=int(total["observation_count"] or 0),
            duplicate_observation_count=int(total["duplicate_observation_count"] or 0),
            vehicles=vehicles,
        )

    def _ensure_schema(self) -> None:
        self.connection.execute(
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
                color_signature_json TEXT,
                observation_count INTEGER NOT NULL DEFAULT 0
            )
            """
        )
        self._ensure_column("vehicles", "display_name", "TEXT")
        self.connection.execute(
            """
            CREATE TABLE IF NOT EXISTS observations (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                vehicle_id INTEGER NOT NULL,
                seen_at REAL NOT NULL,
                track_id INTEGER,
                frame_index INTEGER NOT NULL,
                seen_timestamp REAL NOT NULL,
                class_name TEXT NOT NULL,
                confidence REAL NOT NULL,
                bbox_json TEXT NOT NULL,
                center_json TEXT NOT NULL,
                tracker_name TEXT NOT NULL,
                color_signature_json TEXT,
                FOREIGN KEY(vehicle_id) REFERENCES vehicles(id)
            )
            """
        )
        self.connection.execute(
            "CREATE INDEX IF NOT EXISTS idx_observations_vehicle_id ON observations(vehicle_id)"
        )
        self.connection.execute(
            "CREATE INDEX IF NOT EXISTS idx_vehicles_updated_at ON vehicles(updated_at)"
        )
        self.connection.commit()

    @classmethod
    def _match_score(
        cls,
        row: sqlite3.Row,
        detection: TrackedDetection,
        color_signature: Any | None,
    ) -> float:
        stored_signature = cls._signature_from_json(row["color_signature_json"])
        color_score = cls._correlation(stored_signature, color_signature)
        class_score = 1.0 if row["class_name"] == detection.class_name else 0.0
        size_score = cls._size_similarity(cls._bbox_from_json(row["bbox_json"]), detection.bbox)
        observation_score = min(1.0, float(row["observation_count"] or 0) / 8.0)
        confidence_score = max(0.0, min(1.0, detection.confidence))
        return (
            0.56 * color_score
            + 0.16 * class_score
            + 0.12 * size_score
            + 0.08 * observation_score
            + 0.08 * confidence_score
        )

    @staticmethod
    def _detection_payload(detection: TrackedDetection) -> dict[str, str]:
        return {
            "bbox_json": json.dumps(list(detection.bbox)),
            "center_json": json.dumps(list(detection.center)),
        }

    @staticmethod
    def _signature_json(color_signature: Any | None) -> str | None:
        if color_signature is None:
            return None
        if hasattr(color_signature, "tolist"):
            color_signature = color_signature.tolist()
        return json.dumps([float(value) for value in color_signature])

    @staticmethod
    def _signature_from_json(value: str | None) -> list[float] | None:
        if not value:
            return None
        try:
            return [float(item) for item in json.loads(value)]
        except (TypeError, ValueError, json.JSONDecodeError):
            return None

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
        rows = self.connection.execute(f"PRAGMA table_info({table_name})").fetchall()
        if any(row["name"] == column_name for row in rows):
            return
        self.connection.execute(f"ALTER TABLE {table_name} ADD COLUMN {column_name} {column_type}")

    @staticmethod
    def _correlation(first: Any | None, second: Any | None) -> float:
        if first is None or second is None:
            return 0.0
        if hasattr(second, "tolist"):
            second = second.tolist()
        first_values = [float(value) for value in first]
        second_values = [float(value) for value in second]
        if len(first_values) != len(second_values) or not first_values:
            return 0.0

        first_mean = sum(first_values) / len(first_values)
        second_mean = sum(second_values) / len(second_values)
        numerator = 0.0
        first_denominator = 0.0
        second_denominator = 0.0
        for first_value, second_value in zip(first_values, second_values):
            first_delta = first_value - first_mean
            second_delta = second_value - second_mean
            numerator += first_delta * second_delta
            first_denominator += first_delta * first_delta
            second_denominator += second_delta * second_delta
        denominator = (first_denominator * second_denominator) ** 0.5
        if denominator <= 0:
            return 0.0
        return max(0.0, min(1.0, numerator / denominator))

    @staticmethod
    def _size_similarity(
        first: tuple[float, float, float, float],
        second: tuple[float, float, float, float],
    ) -> float:
        first_w = max(1.0, first[2] - first[0])
        first_h = max(1.0, first[3] - first[1])
        second_w = max(1.0, second[2] - second[0])
        second_h = max(1.0, second[3] - second[1])
        first_area = first_w * first_h
        second_area = second_w * second_h
        area = min(first_area, second_area) / max(first_area, second_area)
        first_aspect = first_w / first_h
        second_aspect = second_w / second_h
        aspect = min(first_aspect, second_aspect) / max(first_aspect, second_aspect)
        return float(0.7 * area + 0.3 * aspect)
